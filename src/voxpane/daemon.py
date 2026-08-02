"""voxpaned — the resident STT daemon — milestone M5.

Holds a ``faster-whisper`` model in memory behind a unix socket at
``paths.socket_path()`` so per-utterance cost is transcription only. The CLI is a
thin client (:func:`voxpane.transcriber.transcribe`); if the socket is absent it
falls back to the M1 ``whisper-cli`` subprocess path, so the tool never
hard-fails.

Protocol: one JSON request line in, one JSON response line out.
  -> {"wav": "/tmp/vp-1.wav", "language": "en", "initial_prompt": "..."}
  <- {"text": "..."}  |  {"error": "..."}

Target: p50 from key-release to delivered text under 1.2 s for a 10 s utterance.
Ship a ``systemd --user`` unit (see ``systemd/voxpaned.service``).
"""

from __future__ import annotations

import json
import socket
import sys
from collections.abc import Callable
from typing import Any

from . import config, paths

# transcribe_fn(wav, language, initial_prompt) -> text
TranscribeFn = Callable[[str, "str | None", "str | None"], str]


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


def _handle_request(req: dict[str, Any], transcribe_fn: TranscribeFn) -> dict[str, Any]:
    try:
        text = transcribe_fn(req["wav"], req.get("language"), req.get("initial_prompt"))
        return {"text": text.strip()}
    except Exception as exc:  # report any failure to the client; never crash the loop
        return {"error": str(exc)}


def _serve(server: socket.socket, transcribe_fn: TranscribeFn) -> None:
    while True:
        conn, _ = server.accept()
        with conn:
            line = _recv_line(conn)
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                conn.sendall(b'{"error": "bad request"}\n')
                continue
            resp = _handle_request(req, transcribe_fn)
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))


def _make_transcribe_fn(model: Any, whisper_cfg: dict[str, Any]) -> TranscribeFn:
    def _fn(wav: str, language: str | None, initial_prompt: str | None) -> str:
        segments, _info = model.transcribe(
            wav,
            language=language or whisper_cfg.get("language", "en"),
            initial_prompt=initial_prompt or None,
        )
        return "".join(seg.text for seg in segments)

    return _fn


def serve() -> int:
    """Load the model once, then serve transcription requests over the socket."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "voxpaned: faster-whisper is not installed.\n"
            "  install the daemon extra:  uv tool install --force 'voxpane[daemon]'",
            file=sys.stderr,
        )
        return 1

    cfg = config.load()
    whisper_cfg = cfg["whisper"]
    model_name = whisper_cfg.get("daemon_model", "large-v3-turbo")
    print(f"voxpaned: loading {model_name} (int8, cpu)…", file=sys.stderr)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")

    paths.ensure(paths.runtime_dir())
    sock_path = paths.socket_path()
    try:
        sock_path.unlink()
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(4)
    print(f"voxpaned: listening on {sock_path}", file=sys.stderr)

    try:
        _serve(server, _make_transcribe_fn(model, whisper_cfg))
    except KeyboardInterrupt:
        return 0
    finally:
        server.close()
        try:
            sock_path.unlink()
        except FileNotFoundError:
            pass
    return 0
