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

import shutil
import subprocess
import time
from typing import Any


def deliver(text: str, cfg: dict[str, Any], *, submit: bool = False) -> str:
    """Deliver ``text`` per ``delivery.mode``; press Enter only if ``submit``.

    Returns a short human status of what happened (for the toast). Falls back to
    the clipboard rather than raising when a target is unreachable.
    """
    mode = cfg["delivery"]["mode"]
    if mode == "tmux":
        return _deliver_tmux(text, cfg, submit=submit)
    if mode == "focus":
        return _deliver_focus(text, cfg)
    return _deliver_clipboard(text)


def _deliver_clipboard(text: str) -> str:
    to_clipboard(text)
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
    if not shutil.which("tmux") or not _tmux_pane_exists(target):
        to_clipboard(text)
        return f"tmux pane {target} gone — copied to clipboard"

    # -l = literal (or "Enter"/"Space" become key names); -- ends option parsing.
    subprocess.run(["tmux", "send-keys", "-t", target, "-l", "--", text], check=True)
    if submit:
        # No -l here: "Enter" must be interpreted as the key.
        subprocess.run(["tmux", "send-keys", "-t", target, "Enter"], check=True)
    return f"sent to tmux {target}" + (" + Enter" if submit else "")


def _deliver_focus(text: str, cfg: dict[str, Any]) -> str:
    to_clipboard(text)
    delay_ms = int(cfg["delivery"].get("focus_paste_delay_ms", 80))
    time.sleep(delay_ms / 1000)
    if not shutil.which("wtype"):
        return "copied to clipboard (wtype missing)"
    # Ctrl+Shift+V paste into the focused window.
    subprocess.run(
        ["wtype", "-M", "ctrl", "-M", "shift", "-k", "v", "-m", "shift", "-m", "ctrl"],
        check=True,
    )
    return "pasted into focused window"


def to_clipboard(text: str) -> None:
    """``wl-copy`` the text. The universal fallback (M1)."""
    if not shutil.which("wl-copy"):
        raise RuntimeError("wl-copy not found — install wl-clipboard (see: voxpane doctor)")
    subprocess.run(["wl-copy"], input=text, text=True, check=True)
