"""Audio capture — milestone M1.

Records from the configured source to a temp ``vp-<ts>.wav`` at 16 kHz mono s16.

Linux (PipeWire/PulseAudio): a ``pw-record``/``parecord`` subprocess. Hard constraints:
  * Stop it with SIGINT, never SIGKILL — SIGKILL leaves the WAV header unfinalised.
  * Enforce ``audio.max_seconds`` via ``timeout --signal=INT`` for a clean auto-stop.

macOS / Windows (sounddevice): there is no ``pw-record`` (and on Windows ``os.kill``
terminates rather than signals), so capture runs in a detached ``voxpane.sdcapture``
worker that finalises the WAV on a filesystem stop-file — see ``_start_sd_worker`` /
``_stop_sd_worker``. Selected by capability: used whenever ``_record_argv`` finds no
PipeWire/PulseAudio tool.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import osutil, paths


def _read_state() -> dict[str, Any] | None:
    f = paths.record_state_file()
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_state(state: dict[str, Any]) -> None:
    paths.ensure(paths.runtime_dir())
    paths.record_state_file().write_text(json.dumps(state))
    paths.record_pid_file().write_text(str(state["pid"]))


def _clear_state() -> None:
    for f in (paths.record_state_file(), paths.record_pid_file()):
        try:
            f.unlink()
        except FileNotFoundError:
            pass


def _win_pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                         capture_output=True, text=True)
    return f" {pid} " in out.stdout or f"\t{pid}\t" in out.stdout


def _pid_alive(pid: int) -> bool:
    if osutil.IS_WINDOWS:
        # os.kill(pid, 0) TERMINATES the process on Windows — must not use it here.
        return _win_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wav_path() -> Path:
    """A fresh temp WAV path — ``%TEMP%`` on Windows, ``/tmp`` on Linux."""
    return Path(tempfile.gettempdir()) / f"vp-{int(time.time())}.wav"


def _sd_stop_file() -> Path:
    return paths.runtime_dir() / "record.stop"


# WAV-file recorders we know how to drive, in preference order: PipeWire first,
# then the PulseAudio equivalent (pure-Pulse systems have no pw-record).
_RECORDERS = ("pw-record", "parecord")


def _running_recorder() -> str | None:
    """The recorder binary currently running (by exact process name), or None."""
    if not shutil.which("pgrep"):
        return None
    for tool in _RECORDERS:
        # Match the process NAME exactly (-x), not the full cmdline (-f): -f would
        # false-positive on any process whose args merely contain the name.
        if subprocess.run(["pgrep", "-x", tool], capture_output=True).returncode == 0:
            return tool
    return None


def _record_argv(rate: int, source: str, wav: Path) -> list[str] | None:
    """Argv to record 16 kHz mono s16 WAV to ``wav``. Prefers PipeWire's ``pw-record``,
    falls back to PulseAudio's ``parecord``. None if neither is installed."""
    targeted = bool(source) and source != "default"
    if shutil.which("pw-record"):
        cmd = ["pw-record", f"--rate={rate}", "--channels=1", "--format=s16"]
        if targeted:
            cmd.append(f"--target={source}")
        cmd.append(str(wav))
        return cmd
    if shutil.which("parecord"):
        cmd = ["parecord", f"--rate={rate}", "--channels=1", "--format=s16le",
               "--file-format=wav"]
        if targeted:
            cmd.append(f"--device={source}")
        cmd.append(str(wav))
        return cmd
    return None


def is_recording() -> bool:
    state = _read_state()
    if state and _pid_alive(int(state["pid"])):
        return True
    return _running_recorder() is not None


def _start_sd_worker(rate: int, max_seconds: int, source: str, wav: Path) -> Path:
    """Spawn the detached sounddevice capture worker (macOS/Windows have no pw-record)."""
    import importlib.util

    if importlib.util.find_spec("sounddevice") is None:
        extra = "windows" if osutil.IS_WINDOWS else "macos"
        raise RuntimeError(
            f"sounddevice not installed — pip install voxpane[{extra}]; see: voxpane doctor"
        )
    paths.ensure(paths.runtime_dir())
    stop_file = _sd_stop_file()
    stop_file.unlink(missing_ok=True)  # clear any stale sentinel
    argv = [sys.executable, "-m", "voxpane.sdcapture",
            str(wav), str(rate), str(max_seconds), str(stop_file)]
    if source and source != "default":
        argv.append(source)
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **osutil.detached_kwargs(),
    )
    _write_state({"wav": str(wav), "pid": proc.pid, "tool": "sdcapture",
                  "stop_file": str(stop_file), "started_at": time.time()})
    return wav


def start(cfg: dict[str, Any]) -> Path:
    """Begin recording in the background and return the target WAV path.

    Idempotent: if a recording is already running, returns its WAV without
    starting a second one.
    """
    if is_recording():
        existing = _read_state()
        if existing:
            return Path(existing["wav"])

    rate = int(cfg["audio"]["rate"])
    max_seconds = int(cfg["audio"]["max_seconds"])
    source = str(cfg["audio"].get("source", "default"))
    wav = _wav_path()

    # PipeWire/PulseAudio subprocess if available (Linux); otherwise the sounddevice
    # capture worker (macOS/Windows, or a Linux box without those tools).
    rec = _record_argv(rate, source, wav)
    if rec is None:
        return _start_sd_worker(rate, max_seconds, source, wav)
    tool = rec[0]

    # A hard ceiling on recording length; SIGINT (not KILL) so the WAV stays valid.
    cmd = rec
    if max_seconds > 0 and shutil.which("timeout"):
        cmd = ["timeout", "--signal=INT", str(max_seconds), *rec]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # survive the CLI process exiting
    )
    _write_state({"wav": str(wav), "pid": proc.pid, "tool": tool, "started_at": time.time()})
    return wav


def _stop_sd_worker(timeout_s: float) -> Path | None:
    """Signal the sounddevice worker via the stop-file and wait for it to finalise."""
    state = _read_state()
    if not state:
        return None
    stop_file = Path(state.get("stop_file") or _sd_stop_file())
    stop_file.write_text("stop")  # tell the worker to finalise the WAV and exit
    wav = Path(state["wav"]) if state.get("wav") else None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not stop_file.exists() or not _pid_alive(int(state["pid"])):
            break  # worker acked (deleted the sentinel) or exited
        time.sleep(0.05)
    stop_file.unlink(missing_ok=True)
    _clear_state()
    return wav


def stop(timeout_s: float = 5.0) -> Path | None:
    """Stop the running recorder and return the finalised WAV path, or ``None`` if
    nothing was recording. The sounddevice worker (macOS/Windows) uses the stop-file;
    the PipeWire/PulseAudio subprocess is SIGINT'd."""
    state = _read_state()
    if state and state.get("tool") == "sdcapture":
        return _stop_sd_worker(timeout_s)
    running = _running_recorder()
    if not state and not running:
        return None

    # SIGINT, NEVER SIGKILL — SIGKILL leaves the WAV header unfinalised. Signal the
    # exact recorder that's running (from state, else whatever's live, else default).
    tool = (state or {}).get("tool") or running or "pw-record"
    if shutil.which("pkill"):
        subprocess.run(["pkill", "-INT", "-x", tool], capture_output=True)
    elif state:
        try:
            os.kill(int(state["pid"]), signal.SIGINT)
        except ProcessLookupError:
            pass

    wav = Path(state["wav"]) if state else None

    # Wait for the recorder to exit so the header is flushed before anyone reads it.
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if state and _pid_alive(int(state["pid"])):
            time.sleep(0.05)
            continue
        if _running_recorder():
            time.sleep(0.05)
            continue
        break

    _clear_state()
    return wav
