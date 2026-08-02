"""Hands-free listen mode — a continuous VAD loop.

Auto-started per Claude session (SessionStart/End hooks). Captures the mic
continuously, detects speech with webrtcvad, and when you stop talking for
``endpoint_silence_ms`` it transcribes the utterance (via the daemon),
post-processes it, delivers it to the focused window, and auto-submits — no
push-to-talk.

Anti-feedback: the loop ignores the mic while the Dot is speaking (the speaking
marker) plus a short guard, so it never transcribes its own voice. Say one of the
``stop_words`` and it hushes the Dot instead of sending text.

The endpointing state machine (:class:`Endpointer`) is pure and unit-tested; the
live capture/transcribe glue needs a real mic to validate.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import paths

FRAME_MS = 20
RATE = 16000
_BYTES_PER_FRAME = int(RATE * FRAME_MS / 1000) * 2  # 640: s16 mono, 20 ms


class Endpointer:
    """Turn a stream of (frame, is_speech) into complete utterances.

    Emits the buffered PCM once the speaker has been silent for ``silence_ms``
    (or the utterance hits ``max_ms``); drops anything shorter than
    ``min_speech_ms`` (coughs, clicks).
    """

    def __init__(self, frame_ms: int, silence_ms: int, min_speech_ms: int, max_ms: int):
        self.silence_frames = max(1, silence_ms // frame_ms)
        self.min_speech_frames = max(1, min_speech_ms // frame_ms)
        self.max_frames = max(1, max_ms // frame_ms)
        self.reset()

    def reset(self) -> None:
        self._buf: list[bytes] = []
        self._voiced = 0
        self._trailing_silence = 0
        self.active = False

    def process(self, frame: bytes, is_speech: bool) -> bytes | None:
        if not self.active:
            if is_speech:
                self.active = True
                self._buf = [frame]
                self._voiced = 1
                self._trailing_silence = 0
            return None

        self._buf.append(frame)
        if is_speech:
            self._voiced += 1
            self._trailing_silence = 0
        else:
            self._trailing_silence += 1

        if self._trailing_silence >= self.silence_frames or len(self._buf) >= self.max_frames:
            audio = b"".join(self._buf)
            enough = self._voiced >= self.min_speech_frames
            self.reset()
            return audio if enough else None
        return None


# --------------------------------------------------- listener process & ref-count

def _read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def is_listening() -> bool:
    pid = _read_pid(paths.listener_pid_file())
    return pid is not None and _alive(pid)


def _sessions() -> set[str]:
    try:
        return {s for s in paths.listen_sessions_file().read_text().split() if s}
    except OSError:
        return set()


def _write_sessions(sessions: set[str]) -> None:
    paths.ensure(paths.runtime_dir())
    paths.listen_sessions_file().write_text(" ".join(sorted(sessions)))


def ensure(session_id: str, cfg: dict[str, Any]) -> None:
    """A Claude session started: register it and start the listener if needed."""
    if not cfg.get("listen", {}).get("enabled", False):
        return
    sessions = _sessions()
    sessions.add(session_id)
    _write_sessions(sessions)
    if not is_listening():
        _spawn_listener()


def release(session_id: str) -> None:
    """A Claude session ended: unregister it and stop the listener if it was last."""
    sessions = _sessions()
    sessions.discard(session_id)
    _write_sessions(sessions)
    if not sessions:
        stop()


def stop() -> None:
    pid = _read_pid(paths.listener_pid_file())
    if pid and _alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    _unlink(paths.listener_pid_file())


def _spawn_listener() -> None:
    # Spawn with the ENV's python (sys.prefix/bin/python), not sys.executable: uv
    # venvs symlink the interpreter to the base python, so sys.executable can point
    # outside the venv (no voxpane/webrtcvad). sys.prefix keeps the venv packages.
    # Capture the child's stderr to a log so a silent early exit is diagnosable.
    env_python = os.path.join(sys.prefix, "bin", "python")
    python = env_python if os.path.exists(env_python) else sys.executable
    try:
        paths.ensure(paths.state_dir())
        err = open(paths.state_dir() / "listen.log", "ab")  # noqa: SIM115
    except OSError:
        err = subprocess.DEVNULL
    subprocess.Popen(
        [python, "-m", "voxpane", "listen", "--run"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=err,
        start_new_session=True,  # outlive the hook process
    )


# ---------------------------------------------------------------- the live loop

def _audio_command() -> list[str]:
    import shutil

    if shutil.which("pw-cat"):
        return ["pw-cat", "--record", "--rate", str(RATE), "--channels", "1",
                "--format", "s16", "--raw", "-"]
    return ["parec", f"--rate={RATE}", "--channels=1", "--format=s16le"]


def _frames(proc: subprocess.Popen) -> Iterator[bytes]:
    assert proc.stdout is not None
    while True:
        frame = proc.stdout.read(_BYTES_PER_FRAME)
        if not frame or len(frame) < _BYTES_PER_FRAME:
            break
        yield frame


def _pcm_to_wav(pcm: bytes, path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)


def is_stop_word(text: str, cfg: dict[str, Any]) -> bool:
    cleaned = text.strip().lower().strip(".!?,")
    return cleaned in {w.lower() for w in cfg["listen"].get("stop_words", [])}


def handle_utterance(pcm: bytes, cfg: dict[str, Any]) -> str | None:
    """Transcribe and act on one utterance. Returns the delivered text, or None."""
    from . import config as config_mod
    from . import deliver, hush, postprocess, transcriber

    wav = paths.runtime_dir() / "listen-utt.wav"
    _pcm_to_wav(pcm, wav)
    try:
        text = transcriber.transcribe(wav, cfg)
    except RuntimeError:
        return None
    finally:
        _unlink(wav)

    if not text:
        return None
    if is_stop_word(text, cfg):
        hush.hush()
        return None

    rewritten = postprocess.apply(text, config_mod.load_commands(), cfg)
    submit = cfg["listen"].get("auto_submit", True) or rewritten.submit
    deliver.deliver(rewritten.text, cfg, submit=submit)
    return rewritten.text


def run(cfg: dict[str, Any] | None = None) -> int:
    from . import config as config_mod

    try:
        import webrtcvad
    except ImportError:
        print(
            "voxpane listen: webrtcvad not installed — "
            "uv tool install --force 'voxpane[daemon,listen]'",
            file=sys.stderr,
        )
        return 1

    cfg = cfg or config_mod.load()
    lc = cfg["listen"]
    vad = webrtcvad.Vad(int(lc.get("vad_aggressiveness", 2)))
    endpointer = Endpointer(
        FRAME_MS,
        int(lc["endpoint_silence_ms"]),
        int(lc["min_speech_ms"]),
        int(lc["max_utterance_seconds"]) * 1000,
    )
    guard = lc.get("post_speak_guard_ms", 700) / 1000

    paths.ensure(paths.runtime_dir())
    paths.listener_pid_file().write_text(str(os.getpid()))
    stop_requested = {"v": False}
    signal.signal(signal.SIGTERM, lambda *_: stop_requested.__setitem__("v", True))
    proc = subprocess.Popen(_audio_command(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    last_speak = 0.0
    try:
        for frame in _frames(proc):
            if stop_requested["v"]:
                break
            # Anti-feedback: don't listen to the Dot, or its echo tail.
            if paths.speaking_marker().exists():
                last_speak = time.monotonic()
                endpointer.reset()
                continue
            if time.monotonic() - last_speak < guard:
                endpointer.reset()
                continue
            utterance = endpointer.process(frame, vad.is_speech(frame, RATE))
            if utterance is not None:
                handle_utterance(utterance, cfg)
    finally:
        proc.terminate()
        _unlink(paths.listener_pid_file())
    return 0
