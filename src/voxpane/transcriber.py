"""Speech-to-text — milestones M1 (subprocess) and M5 (daemon).

M1: shell out to ``whisper-cli`` per utterance (simple, ~model-load latency).
M5: the daemon holds a ``faster-whisper`` model in RAM; the CLI talks to it over
    the unix socket and falls back to this subprocess path if the socket is
    absent, so the tool never hard-fails.

Both honour ``whisper.initial_prompt`` (biases the decoder toward the project
vocabulary; hard-capped at 224 tokens — we warn past a rough word estimate).
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import config as config_mod
from . import paths

_PROMPT_TOKEN_CAP = 224


def transcribe_file(wav: Path, cfg: dict[str, Any]) -> str:
    """Transcribe ``wav`` via ``whisper-cli`` and return plain text."""
    binary = cfg["whisper"].get("binary", "whisper-cli")
    if not shutil.which(binary):
        raise RuntimeError(f"{binary} not found — install whisper.cpp (see: voxpane doctor)")

    model = config_mod.model_path(cfg)
    if not model.exists():
        raise RuntimeError(f"whisper model missing: {model}")

    cmd = [
        binary,
        "-m", str(model),
        "-f", str(wav),
        "-l", str(cfg["whisper"].get("language", "en")),
        "-np",  # no prints (suppress system info / progress)
        "-nt",  # no timestamps — just the text
    ]

    threads = int(cfg["whisper"].get("threads", 0))
    if threads > 0:
        cmd += ["-t", str(threads)]

    prompt = (cfg["whisper"].get("initial_prompt") or "").strip()
    if prompt:
        if len(prompt.split()) > _PROMPT_TOKEN_CAP:
            print(
                "[voxpane] warning: whisper.initial_prompt looks longer than the "
                "224-token cap; whisper will truncate it.",
                file=sys.stderr,
            )
        cmd += ["--prompt", prompt]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"{binary} failed: {detail}")

    return result.stdout.strip()


def transcribe_via_daemon(wav: Path, cfg: dict[str, Any]) -> str | None:
    """Ask ``voxpaned`` to transcribe. Returns ``None`` if the daemon is
    unavailable (socket absent, refused, timed out, or it reported an error) so
    the caller can fall back to :func:`transcribe_file`."""
    sock_path = paths.socket_path()
    # No AF_UNIX on Windows (CPython) — always fall back to whisper-cli there.
    if not hasattr(socket, "AF_UNIX") or not sock_path.exists():
        return None

    request = {
        "wav": str(wav),
        "language": cfg["whisper"].get("language", "en"),
        "initial_prompt": (cfg["whisper"].get("initial_prompt") or "").strip(),
    }
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(120)
            client.connect(str(sock_path))
            client.sendall((json.dumps(request) + "\n").encode("utf-8"))
            data = _recv_line(client)
    except OSError:
        return None

    if not data:
        return None
    response = json.loads(data)
    if "error" in response:
        print(f"[voxpane] daemon error, falling back: {response['error']}", file=sys.stderr)
        return None
    return response.get("text", "")


def transcribe(wav: Path, cfg: dict[str, Any]) -> str:
    """Transcribe via the daemon if available, else the subprocess path."""
    text = transcribe_via_daemon(wav, cfg)
    return text if text is not None else transcribe_file(wav, cfg)


def _recv_line(conn: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        buf = conn.recv(4096)
        if not buf:
            break
        chunks.append(buf)
        if b"\n" in buf:
            break
    return b"".join(chunks).decode("utf-8", "replace").split("\n", 1)[0]
