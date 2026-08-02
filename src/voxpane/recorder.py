"""Audio capture via PipeWire — milestone M1.

Records from the configured source to ``/tmp/vp-<ts>.wav`` at 16 kHz mono s16.

Hard constraints (see docs/plans/voxpane-plan.md):
  * Stop ``pw-record`` with SIGINT, never SIGKILL — SIGKILL leaves the WAV header
    unfinalised and the file unreadable (``pkill -INT -f pw-record``).
  * Enforce ``audio.max_seconds`` so a forgotten recording cannot fill the disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def start(cfg: dict[str, Any]) -> Path:
    """Begin recording; write the pid to ``paths.record_pid_file()``; return the
    target WAV path. Returns immediately (recording continues in the background)."""
    raise NotImplementedError("recorder.start — milestone M1")


def stop() -> Path | None:
    """SIGINT the running ``pw-record`` and return the finalised WAV path, or
    ``None`` if nothing was recording."""
    raise NotImplementedError("recorder.stop — milestone M1")


def is_recording() -> bool:
    raise NotImplementedError("recorder.is_recording — milestone M1")
