"""Audio capture via PipeWire — milestone M1.

Records from the configured source to ``/tmp/vp-<ts>.wav`` at 16 kHz mono s16.

Hard constraints (see docs/plans/voxpane-plan.md):
  * Stop ``pw-record`` with SIGINT, never SIGKILL — SIGKILL leaves the WAV header
    unfinalised and the file unreadable.
  * Enforce ``audio.max_seconds`` so a forgotten recording cannot fill the disk;
    we wrap the recorder in ``timeout --signal=INT`` for a clean auto-stop.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from . import paths


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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    wav = Path(f"/tmp/vp-{int(time.time())}.wav")

    rec = _record_argv(rate, source, wav)
    if rec is None:
        raise RuntimeError(
            "no recorder found — install PipeWire (pw-record) or PulseAudio "
            "(parecord); see: voxpane doctor"
        )
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


def stop(timeout_s: float = 5.0) -> Path | None:
    """SIGINT the running recorder and return the finalised WAV path, or ``None``
    if nothing was recording."""
    state = _read_state()
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
