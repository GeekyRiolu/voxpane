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


def _pgrep_pw_record() -> bool:
    if not shutil.which("pgrep"):
        return False
    # Match the process NAME exactly (-x), not the full cmdline (-f): -f would
    # false-positive on any process whose args merely contain "pw-record".
    return subprocess.run(["pgrep", "-x", "pw-record"], capture_output=True).returncode == 0


def is_recording() -> bool:
    state = _read_state()
    if state and _pid_alive(int(state["pid"])):
        return True
    return _pgrep_pw_record()


def start(cfg: dict[str, Any]) -> Path:
    """Begin recording in the background and return the target WAV path.

    Idempotent: if a recording is already running, returns its WAV without
    starting a second one.
    """
    if is_recording():
        existing = _read_state()
        if existing:
            return Path(existing["wav"])

    if not shutil.which("pw-record"):
        raise RuntimeError("pw-record not found — install pipewire (see: voxpane doctor)")

    rate = int(cfg["audio"]["rate"])
    max_seconds = int(cfg["audio"]["max_seconds"])
    source = str(cfg["audio"].get("source", "default"))
    wav = Path(f"/tmp/vp-{int(time.time())}.wav")

    rec = ["pw-record", f"--rate={rate}", "--channels=1", "--format=s16"]
    if source and source != "default":
        rec.append(f"--target={source}")
    rec.append(str(wav))

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
    _write_state({"wav": str(wav), "pid": proc.pid, "started_at": time.time()})
    return wav


def stop(timeout_s: float = 5.0) -> Path | None:
    """SIGINT the running recorder and return the finalised WAV path, or ``None``
    if nothing was recording."""
    state = _read_state()
    if not state and not _pgrep_pw_record():
        return None

    # SIGINT, NEVER SIGKILL — SIGKILL leaves the WAV header unfinalised.
    if shutil.which("pkill"):
        subprocess.run(["pkill", "-INT", "-f", "pw-record"], capture_output=True)
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
        if _pgrep_pw_record():
            time.sleep(0.05)
            continue
        break

    _clear_state()
    return wav
