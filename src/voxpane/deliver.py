"""Deliver text to the agent — milestone M3. Three modes:

  tmux       ``tmux send-keys -t <target> -l -- <text>`` (literal; the ``-l`` is
             mandatory or "Enter"/"Space" get interpreted as key names). No Enter
             unless auto-submit. Fall back to clipboard with a warning if the
             pane is gone.
  focus      copy to clipboard then Ctrl+Shift+V into the focused window, via the
             detected desktop backend (:mod:`voxpane.desktop` — wtype/xdotool/ydotool)
             after a configurable ~80 ms pre-delay.
  clipboard  clipboard only (wl-copy / xclip / xsel, per backend).

Never auto-submit by default: submitting a mis-transcription is worse than a
wasted keystroke.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

from . import desktop


def deliver(text: str, cfg: dict[str, Any], *, submit: bool = False) -> str:
    """Deliver ``text`` per ``delivery.mode``; press Enter only if ``submit``.

    Returns a short human status of what happened (for the toast). Falls back to
    the clipboard rather than raising when a target is unreachable.
    """
    mode = cfg["delivery"]["mode"]
    if mode == "tmux":
        return _deliver_tmux(text, cfg, submit=submit)
    if mode == "focus":
        return _deliver_focus(text, cfg, submit=submit)
    return _deliver_clipboard(text, cfg)


def _deliver_clipboard(text: str, cfg: dict[str, Any]) -> str:
    to_clipboard(text, cfg)
    return "copied to clipboard"


def _tmux_pane_exists(target: str) -> bool:
    result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", target, "#{pane_id}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() != ""


def _deliver_tmux(text: str, cfg: dict[str, Any], *, submit: bool) -> str:
    target = cfg["delivery"]["tmux_target"]
    if not shutil.which("tmux"):  # e.g. Windows — set [delivery] mode = "focus"/"clipboard"
        to_clipboard(text, cfg)
        return "tmux not installed — copied to clipboard"
    if not _tmux_pane_exists(target):
        to_clipboard(text, cfg)
        return f"tmux pane {target} gone — copied to clipboard"

    # -l = literal (or "Enter"/"Space" become key names); -- ends option parsing.
    subprocess.run(["tmux", "send-keys", "-t", target, "-l", "--", text], check=True)
    if submit:
        # No -l here: "Enter" must be interpreted as the key.
        subprocess.run(["tmux", "send-keys", "-t", target, "Enter"], check=True)
    return f"sent to tmux {target}" + (" + Enter" if submit else "")


def _deliver_focus(text: str, cfg: dict[str, Any], *, submit: bool = False) -> str:
    to_clipboard(text, cfg)
    delay_ms = int(cfg["delivery"].get("focus_paste_delay_ms", 80))
    time.sleep(delay_ms / 1000)
    # Ctrl+Shift+V paste into the focused window, via the desktop backend's typing
    # tool (wtype on Wayland, xdotool on X11, ydotool on GNOME/KDE).
    if not desktop.paste_and_submit(cfg, submit=submit):
        return "copied to clipboard (no typing tool for this desktop)"
    return "pasted into focused window" + (" + Enter" if submit else "")


def to_clipboard(text: str, cfg: dict[str, Any] | None = None) -> None:
    """Copy ``text`` to the clipboard via the desktop backend (``wl-copy`` on Wayland,
    ``xclip``/``xsel`` on X11). The universal delivery fallback."""
    desktop.clipboard_copy(text, cfg)
