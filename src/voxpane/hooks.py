"""Install voxpane's Claude Code hooks — milestone M6.

Merges the PostToolUse and Stop hooks into ``~/.claude/settings.json`` without
clobbering existing hooks: read, back up, merge (idempotently), write. The hook
scripts are copied to the voxpane config hooks dir so settings.json can point at
a stable absolute path regardless of how voxpane was installed.

Scripts ship as ``*.sh`` (bash) and ``*.ps1`` (PowerShell); on Windows we install the
``.ps1`` variants and point the hook command at ``powershell -File``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import osutil, paths

# event -> (script base name, matcher)
_SCRIPTS = {
    "PostToolUse": ("voxpane-post-tool", "*"),
    "Stop": ("voxpane-stop", None),
    "Notification": ("voxpane-notification", None),
    "SessionStart": ("voxpane-session-start", None),
    "SessionEnd": ("voxpane-session-end", None),
}


def _ext() -> str:
    return ".ps1" if osutil.IS_WINDOWS else ".sh"


def _hook_command(script_path: Path) -> str:
    """The settings.json command that runs a hook script for this OS."""
    if osutil.IS_WINDOWS:
        return f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script_path}"'
    return str(script_path)


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _source_hooks_dir() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [here.parents[2] / "hooks", here.parent / "data" / "hooks"]
    probe = "voxpane-stop" + _ext()
    return next((c for c in candidates if (c / probe).is_file()), None)


def _ensure_hook(hooks: dict[str, Any], event: str, command: str, matcher: str | None) -> bool:
    entries = hooks.setdefault(event, [])
    for group in entries:
        for hook in group.get("hooks", []):
            if hook.get("command") == command:
                return False  # already present — idempotent
    group: dict[str, Any] = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        group["matcher"] = matcher
    entries.append(group)
    return True


def install_hooks(settings: Path | None = None, hooks_dest: Path | None = None) -> dict[str, Any]:
    source = _source_hooks_dir()
    if source is None:
        raise RuntimeError("bundled hook scripts not found")

    ext = _ext()
    dest = hooks_dest or (paths.config_dir() / "hooks")
    paths.ensure(dest)
    for base, _ in _SCRIPTS.values():
        script = base + ext
        shutil.copy2(source / script, dest / script)
        if not osutil.IS_WINDOWS:
            (dest / script).chmod(0o755)  # chmod is a no-op on Windows

    settings = settings or settings_path()
    data: dict[str, Any] = {}
    backup: Path | None = None
    if settings.is_file():
        data = json.loads(settings.read_text() or "{}")
        backup = settings.parent / (settings.name + ".voxpane.bak")
        shutil.copy2(settings, backup)

    hooks = data.setdefault("hooks", {})
    added = [
        event
        for event, (base, matcher) in _SCRIPTS.items()
        if _ensure_hook(hooks, event, _hook_command(dest / (base + ext)), matcher)
    ]

    paths.ensure(settings.parent)
    settings.write_text(json.dumps(data, indent=2) + "\n")
    return {"settings": settings, "backup": backup, "added": added, "hooks_dir": dest}
