"""Install the Hyprland push-to-talk keybinding — milestone M2.

Idempotent and format-aware. Omarchy's binding file varies by version: newer
builds use ``bindings.lua`` with an ``o.bind(...)`` helper, older ones
``bindings.conf`` with ``bindd = ...``. We detect which exists and match it, back
up before writing, and skip cleanly if the binding is already present.

Omarchy updates can overwrite ``bindings.conf`` (upstream #1802), so re-running
this is the intended repair. ``hypr/bindings.snippet`` is the human-readable
source of truth; the active line is generated here to match the detected format.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

MODS = "SUPER ALT"
KEY = "V"
DESC = "Toggle voxpane dictation"
CMD = "voxpane toggle"
_MARKER = CMD  # any line invoking `voxpane toggle` means we're already installed
_HEADER = "# voxpane push-to-talk (managed by `voxpane install-bindings`)"


def hypr_dir() -> Path:
    return Path.home() / ".config" / "hypr"


def _conf_line() -> str:
    # bindd = MODS, key, description, dispatcher, args
    return f"bindd = {MODS}, {KEY}, {DESC}, exec, {CMD}"


def _lua_line() -> str:
    return f'o.bind("{MODS}", "{KEY}", "exec, {CMD}", {{ description = "{DESC}" }})'


@dataclass(frozen=True)
class Result:
    status: str          # already | installed | created
    path: Path
    kind: str            # lua | conf
    backup: Path | None
    sourced: bool


def _target(base: Path) -> tuple[Path, str, str]:
    """Pick the file to edit and the line to write, preferring an existing one."""
    lua = base / "bindings.lua"
    conf = base / "bindings.conf"
    if lua.is_file():
        return lua, "lua", _lua_line()
    if conf.is_file():
        return conf, "conf", _conf_line()
    return conf, "conf", _conf_line()  # neither exists -> create a conf file


def _is_sourced(base: Path, target: Path) -> bool:
    main = base / "hyprland.conf"
    return main.is_file() and target.name in main.read_text()


def install(base: Path | None = None) -> Result:
    """Add (or confirm) the keybinding. Idempotent; backs up before writing."""
    base = base or hypr_dir()
    if not base.exists():
        raise RuntimeError(f"{base} not found — is Hyprland configured?")

    path, kind, line = _target(base)
    if path.is_file() and _MARKER in path.read_text():
        return Result("already", path, kind, None, _is_sourced(base, path))

    existed = path.is_file()
    backup: Path | None = None
    if existed:
        backup = path.parent / (path.name + ".voxpane.bak")
        shutil.copy2(path, backup)

    with path.open("a") as fh:
        fh.write(("\n" if existed else "") + f"{_HEADER}\n{line}\n")

    return Result(
        "installed" if existed else "created",
        path,
        kind,
        backup,
        _is_sourced(base, path),
    )
