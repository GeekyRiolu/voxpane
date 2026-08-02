"""On-screen overlay state — drives a Siri-style indicator.

voxpane writes ``{state, text, ts}`` to ``paths.overlay_state_file()`` as it
transitions (listening → thinking → speaking → idle); the shipped eww overlay
(``ui/eww/``) and the waybar module read it via ``voxpane status``. State older
than ``_STALE_S`` is treated as idle so a crashed writer can't pin the UI "on".
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import paths

_STALE_S = 12.0

# state -> (icon, label) for the overlay / waybar.
STATES = {
    "recording": ("🎙", "Recording…"),
    "listening": ("👂", "Listening…"),
    "thinking": ("💭", "Thinking…"),
    "speaking": ("🔊", "Speaking…"),
    "idle": ("", "idle"),
}


def set_state(state: str, text: str = "") -> None:
    """Record the current overlay state. Best-effort; never raises."""
    try:
        paths.ensure(paths.runtime_dir())
        paths.overlay_state_file().write_text(
            json.dumps({"state": state, "text": text, "ts": time.time()})
        )
    except OSError:
        pass


def read_state() -> dict:
    """Return the current ``{state, text}``; idle if unset or stale."""
    try:
        data = json.loads(paths.overlay_state_file().read_text())
    except (OSError, json.JSONDecodeError):
        return {"state": "idle", "text": ""}
    if time.time() - data.get("ts", 0) > _STALE_S:
        return {"state": "idle", "text": ""}
    return {"state": data.get("state", "idle"), "text": data.get("text", "")}


def clear() -> None:
    set_state("idle", "")


def _shipped_pet_dirs() -> list[Path]:
    here = Path(__file__).resolve()
    return [here.parents[2] / "ui" / "eww" / "pet", here.parent / "data" / "ui" / "eww" / "pet"]


def sprite_path(state: str) -> str:
    """Absolute path to the pixel-pet sprite for ``state``.

    Prefers a user override in ``~/.config/voxpane/pet/<state>.{gif,png,svg}``,
    else the shipped SVG; falls back to the idle sprite for unknown states.
    """
    candidates = [state, "idle"]
    user_dir = paths.config_dir() / "pet"
    for name in candidates:
        for ext in (".gif", ".png", ".svg"):
            override = user_dir / f"{name}{ext}"
            if override.is_file():
                return str(override)
    for base in _shipped_pet_dirs():
        for name in candidates:
            shipped = base / f"{name}.svg"
            if shipped.is_file():
                return str(shipped)
    return ""
