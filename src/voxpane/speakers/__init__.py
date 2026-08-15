"""Echo Dot speaker backends and the ordered fallback chain — milestone M8.

Backends are tried in the order given by ``speak.backends`` (default
``["alexa", "bluetooth", "notify"]``). Every failure falls through to the next;
the final ``notify`` backend must never fail. A single lock
(``paths.speak_lock_file()``) serialises concurrent utterances so two Claude Code
panes finishing at once do not talk over each other.
"""

from __future__ import annotations

import contextlib
from typing import Any

from .. import osutil, paths

if not osutil.IS_WINDOWS:
    import fcntl  # POSIX-only; Windows uses a best-effort no-op lock (below)
from .alexa import AlexaSpeaker
from .base import Speaker, SpeakerError
from .bluetooth import BluetoothSpeaker
from .notify import NotifySpeaker

__all__ = ["Speaker", "SpeakerError", "get_backend", "speak_with_fallback"]

_BACKENDS: dict[str, type[Speaker]] = {
    "alexa": AlexaSpeaker,
    "bluetooth": BluetoothSpeaker,
    "notify": NotifySpeaker,
}


def get_backend(name: str, cfg: dict[str, Any]) -> Speaker:
    """Instantiate a backend by name (``alexa`` | ``bluetooth`` | ``notify``)."""
    try:
        return _BACKENDS[name](cfg)
    except KeyError:
        raise ValueError(f"unknown speaker backend: {name}") from None


def _lock_acquire(handle) -> None:
    if osutil.IS_WINDOWS:
        import msvcrt
        handle.write(" ")  # msvcrt.locking needs a byte range to lock
        handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        except OSError:
            pass  # best-effort: proceed even if we couldn't take the lock
    else:
        fcntl.flock(handle, fcntl.LOCK_EX)


def _lock_release(handle) -> None:
    try:
        if osutil.IS_WINDOWS:
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass


@contextlib.contextmanager
def _speak_lock():
    """Serialise utterances across concurrent sessions (best-effort file lock):
    ``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows."""
    lock_path = paths.speak_lock_file()
    paths.ensure(lock_path.parent)
    handle = open(lock_path, "w")  # noqa: SIM115 - held for the context's duration
    try:
        _lock_acquire(handle)
        yield
    finally:
        _lock_release(handle)
        handle.close()


def speak_with_fallback(text: str, cfg: dict[str, Any]) -> str:
    """Try each configured backend in order under the speak lock; return the name
    of the backend that spoke. Never raises — ``notify`` is the floor."""
    order = cfg["speak"].get("backends", ["alexa", "bluetooth", "notify"])
    marker = paths.speaking_marker()
    with _speak_lock():
        paths.ensure(marker.parent)
        marker.touch()
        try:
            for name in order:
                try:
                    backend = get_backend(name, cfg)
                except ValueError:
                    continue
                if not backend.available():
                    continue
                try:
                    backend.speak(text)
                    return name
                except SpeakerError:
                    continue
            # Floor: guarantee something surfaces even if "notify" wasn't listed.
            NotifySpeaker(cfg).speak(text)
            return "notify"
        finally:
            try:
                marker.unlink()
            except FileNotFoundError:
                pass
