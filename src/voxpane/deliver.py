"""Deliver text to the agent — milestone M3. Three modes:

  tmux       ``tmux send-keys -t <target> -l -- <text>`` (literal; the ``-l`` is
             mandatory or "Enter"/"Space" get interpreted as key names). No Enter
             unless auto-submit. Fall back to clipboard with a warning if the
             pane is gone.
  focus      ``wl-copy`` then paste into the focused window with
             ``wtype -M ctrl -M shift -k v -m shift -m ctrl`` after a configurable
             ~80 ms pre-delay.
  clipboard  ``wl-copy`` only.

Never auto-submit by default: submitting a mis-transcription is worse than a
wasted keystroke.
"""

from __future__ import annotations

from typing import Any


def deliver(text: str, cfg: dict[str, Any], *, submit: bool = False) -> None:
    """Deliver ``text`` per ``delivery.mode``; press Enter only if ``submit``."""
    raise NotImplementedError("deliver.deliver — milestone M3")


def to_clipboard(text: str) -> None:
    """``wl-copy`` the text. The universal fallback; should not raise on success."""
    raise NotImplementedError("deliver.to_clipboard — milestone M3")
