"""Speech-to-text — milestones M1 (subprocess) and M5 (daemon).

M1: shell out to ``whisper-cli`` per utterance (simple, ~model-load latency).
M5: the daemon holds a ``faster-whisper`` model (``large-v3-turbo``,
    ``compute_type="int8"`` on CPU) in RAM; the CLI talks to it over the unix
    socket and falls back to this subprocess path if the socket is absent, so the
    tool never hard-fails.

Both paths honour ``whisper.initial_prompt`` (biases the decoder toward the
project vocabulary; hard-capped at 224 tokens — validate and warn past that).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def transcribe_file(wav: Path, cfg: dict[str, Any]) -> str:
    """Transcribe ``wav`` via ``whisper-cli`` and return plain text."""
    raise NotImplementedError("transcriber.transcribe_file — milestone M1")


def transcribe_via_daemon(wav: Path, cfg: dict[str, Any]) -> str | None:
    """Ask ``voxpaned`` to transcribe. Return ``None`` if the socket is absent so
    the caller can fall back to :func:`transcribe_file`."""
    raise NotImplementedError("transcriber.transcribe_via_daemon — milestone M5")
