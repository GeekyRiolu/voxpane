"""Install voxpane's compositor keybinds — milestones M2 / M9+.

Hyprland and Sway can have their binds written directly (idempotent and
format-aware); other desktops (X11 window managers, GNOME, KDE) expose no reliable
cross-DE keybind API, so there we print the exact shortcut to add by hand.

Hyprland: Omarchy's binding file varies by version — newer builds use
``bindings.lua`` with an ``o.bind(...)`` helper, older ones ``bindings.conf`` with
``bindd = ...``. We detect which exists and match it, back up before writing, and
add only the binds not already present. Omarchy updates can overwrite
``bindings.conf`` (upstream #1802), so re-running this is the intended repair.

Sway: binds go in ``~/.config/sway/config.d/voxpane.conf`` (created if needed); we
warn if the main config doesn't ``include`` that directory.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

# (mods, key, description, command) — matched idempotently by command string.
_BINDS = [
    ("SUPER ALT", "V", "Toggle voxpane listening on/off", "voxpane listen --toggle"),
    ("SUPER ALT", "S", "Stop voxpane speaking", "voxpane hush"),
]
_HEADER = "# voxpane keybinds (managed by `voxpane install-bindings`)"

# Human-facing modifier names, and Sway/XKB modifier keysyms.
_PRETTY_MODS = {"SUPER": "Super", "ALT": "Alt", "CTRL": "Ctrl", "SHIFT": "Shift"}
_SWAY_MODS = {"SUPER": "Mod4", "ALT": "Mod1", "CTRL": "Control", "SHIFT": "Shift"}


def hypr_dir() -> Path:
    return Path.home() / ".config" / "hypr"


def sway_dir() -> Path:
    return Path.home() / ".config" / "sway"


def _conf_line(mods: str, key: str, desc: str, cmd: str) -> str:
    return f"bindd = {mods}, {key}, {desc}, exec, {cmd}"


def _lua_line(mods: str, key: str, desc: str, cmd: str) -> str:
    return f'o.bind("{mods}", "{key}", "exec, {cmd}", {{ description = "{desc}" }})'


def _sway_line(mods: str, key: str, _desc: str, cmd: str) -> str:
    mod = "+".join(_SWAY_MODS.get(m, m) for m in mods.split())
    return f"bindsym {mod}+{key.lower()} exec {cmd}"


def manual_lines() -> list[str]:
    """Human-readable ``Super+Alt+V  →  command`` pairs, for desktops we can't
    auto-bind — the user adds these in their system keyboard settings."""
    out = []
    for mods, key, _desc, cmd in _BINDS:
        combo = "+".join(_PRETTY_MODS.get(m, m) for m in mods.split()) + f"+{key}"
        out.append(f"{combo}  →  {cmd}")
    return out


@dataclass(frozen=True)
class Result:
    status: str          # already | installed | created | manual
    path: Path | None
    kind: str            # lua | conf | sway | manual
    backup: Path | None = None
    sourced: bool = False
    added: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)


def _target(base: Path):
    lua, conf = base / "bindings.lua", base / "bindings.conf"
    if lua.is_file():
        return lua, "lua", _lua_line
    return conf, "conf", _conf_line  # existing conf, or create one


def _is_sourced(base: Path, target: Path) -> bool:
    main = base / "hyprland.conf"
    return main.is_file() and target.name in main.read_text()


def _append_binds(path: Path, render, to_add) -> Path | None:
    """Back up an existing file, append the header + rendered binds. Returns the
    backup path (or None if the file was freshly created)."""
    existed = path.is_file()
    backup: Path | None = None
    if existed:
        backup = path.parent / (path.name + ".voxpane.bak")
        shutil.copy2(path, backup)
    lines = [render(*bind) for bind in to_add]
    with path.open("a") as fh:
        fh.write(("\n" if existed else "") + _HEADER + "\n" + "\n".join(lines) + "\n")
    return backup


def install_hyprland(base: Path | None = None) -> Result:
    base = base or hypr_dir()
    if not base.exists():
        raise RuntimeError(f"{base} not found — is Hyprland configured?")

    path, kind, render = _target(base)
    existing = path.read_text() if path.is_file() else ""
    to_add = [bind for bind in _BINDS if bind[3] not in existing]
    if not to_add:
        return Result("already", path, kind, None, _is_sourced(base, path))

    existed = path.is_file()
    backup = _append_binds(path, render, to_add)
    return Result(
        "installed" if existed else "created",
        path,
        kind,
        backup,
        _is_sourced(base, path),
        [f"{mods} {key}" for mods, key, _desc, _cmd in to_add],
    )


def _sway_sourced(base: Path, target: Path) -> bool:
    main = base / "config"
    if not main.is_file():
        return False
    text = main.read_text()
    return "config.d" in text or target.name in text


def install_sway(base: Path | None = None) -> Result:
    base = base or sway_dir()
    if not base.exists():
        raise RuntimeError(f"{base} not found — is Sway configured?")

    config_d = base / "config.d"
    target = config_d / "voxpane.conf"
    existing = target.read_text() if target.is_file() else ""
    to_add = [bind for bind in _BINDS if bind[3] not in existing]
    if not to_add:
        return Result("already", target, "sway", None, _sway_sourced(base, target))

    existed = target.is_file()
    if not existed:
        config_d.mkdir(parents=True, exist_ok=True)
    backup = _append_binds(target, _sway_line, to_add)
    return Result(
        "installed" if existed else "created",
        target,
        "sway",
        backup,
        _sway_sourced(base, target),
        [f"{mods} {key}" for mods, key, _desc, _cmd in to_add],
    )


def install(base: Path | None = None, backend: str | None = None) -> Result:
    """Install the keybinds for the active desktop, dispatching on the detected
    backend (or an explicit override). Hyprland/Sway write a file; every other
    desktop returns a ``manual`` result carrying the shortcuts to add by hand."""
    from . import config, desktop

    backend = backend or desktop.backend(config.load())
    if backend == desktop.SWAY:
        return install_sway(base)
    if backend == desktop.HYPRLAND:
        return install_hyprland(base)
    return Result("manual", None, "manual", instructions=manual_lines())
