"""voxpaned — the resident STT daemon — milestone M5.

Holds a ``faster-whisper`` model in memory behind a unix socket at
``paths.socket_path()`` so per-utterance latency is transcription-only. The CLI
is a thin client; if the socket is absent it falls back to the M1 subprocess
path, so the tool never hard-fails.

Target: p50 from key-release to delivered text under 1.2 s for a 10 s utterance.
Ship a ``systemd --user`` unit (see ``systemd/voxpaned.service``).
"""

from __future__ import annotations


def serve() -> int:
    """Load the model once, then serve transcription requests over the socket
    until terminated. Returns a process exit code."""
    raise NotImplementedError("daemon.serve — milestone M5")
