"""Install voxpane's Hyprland keybinds — milestones M2 / M9+.

Idempotent and format-aware. Omarchy's binding file varies by version: newer
builds use ``bindings.lua`` with an ``o.bind(...)`` helper, older ones
``bindings.conf`` with ``bindd = ...``. We detect which exists and match it, back
up before writing, and add only the binds not already present.

Omarchy updates can overwrite ``bindings.conf`` (upstream #1802), so re-running
this is the intended repair. ``hypr/bindings.snippet`` is the human-readable
source of truth; the active lines are generated here to match the detected format.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

# (mods, key, description, command) — matched idempotently by command string.
_BINDS = [
    ("SUPER ALT", "V", "Toggle voxpane dictation", "voxpane toggle"),
    ("SUPER ALT", "S", "Stop voxpane speaking", "voxpane hush"),
]
_HEADER = "# voxpane keybinds (managed by `voxpane install-bindings`)"


def hypr_dir() -> Path:
    return Path.home() / ".config" / "hypr"


def _conf_line(mods: str, key: str, desc: str, cmd: str) -> str:
    return f"bindd = {mods}, {key}, {desc}, exec, {cmd}"


def _lua_line(mods: str, key: str, desc: str, cmd: str) -> str:
    return f'o.bind("{mods}", "{key}", "exec, {cmd}", {{ description = "{desc}" }})'


@dataclass(frozen=True)
class Result:
    status: str          # already | installed | created
    path: Path
    kind: str            # lua | conf
    backup: Path | None
    sourced: bool
    added: list[str] = field(default_factory=list)


def _target(base: Path):
    lua, conf = base / "bindings.lua", base / "bindings.conf"
    if lua.is_file():
        return lua, "lua", _lua_line
    return conf, "conf", _conf_line  # existing conf, or create one


def _is_sourced(base: Path, target: Path) -> bool:
    main = base / "hyprland.conf"
    return main.is_file() and target.name in main.read_text()


def install(base: Path | None = None) -> Result:
    base = base or hypr_dir()
    if not base.exists():
        raise RuntimeError(f"{base} not found — is Hyprland configured?")

    path, kind, render = _target(base)
    existing = path.read_text() if path.is_file() else ""
    to_add = [bind for bind in _BINDS if bind[3] not in existing]
    if not to_add:
        return Result("already", path, kind, None, _is_sourced(base, path))

    existed = path.is_file()
    backup: Path | None = None
    if existed:
        backup = path.parent / (path.name + ".voxpane.bak")
        shutil.copy2(path, backup)

    lines = [render(*bind) for bind in to_add]
    with path.open("a") as fh:
        fh.write(("\n" if existed else "") + _HEADER + "\n" + "\n".join(lines) + "\n")

    return Result(
        "installed" if existed else "created",
        path,
        kind,
        backup,
        _is_sourced(base, path),
        [f"{mods} {key}" for mods, key, _desc, _cmd in to_add],
    )
