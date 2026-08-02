"""Echo Dot speaker backends and the ordered fallback chain — milestone M8.

Backends are tried in the order given by ``speak.backends`` (default
``["alexa", "bluetooth", "notify"]``). Every failure falls through to the next;
the final ``notify`` backend must never fail. A single lock
(``paths.speak_lock_file()``) serialises concurrent utterances so two Claude Code
panes finishing at once do not talk over each other.
"""

from __future__ import annotations

from typing import Any

from .base import Speaker

__all__ = ["Speaker", "get_backend", "speak_with_fallback"]


def get_backend(name: str, cfg: dict[str, Any]) -> Speaker:
    """Instantiate a backend by name (``alexa`` | ``bluetooth`` | ``notify``)."""
    raise NotImplementedError("speakers.get_backend — milestone M8")


def speak_with_fallback(text: str, cfg: dict[str, Any]) -> str:
    """Try each configured backend in order under the speak lock; return the name
    of the backend that succeeded. Never raises (``notify`` is the floor)."""
    raise NotImplementedError("speakers.speak_with_fallback — milestone M8")
