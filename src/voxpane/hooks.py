"""Install voxpane's Claude Code hooks — milestone M6.

Merges the PostToolUse and Stop hooks into ``~/.claude/settings.json`` without
clobbering existing hooks: read, back up, merge (idempotently), write. The hook
scripts are copied to ``~/.config/voxpane/hooks/`` so settings.json can point at
a stable absolute path regardless of how voxpane was installed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import paths

_SCRIPTS = {
    "PostToolUse": ("voxpane-post-tool.sh", "*"),
    "Stop": ("voxpane-stop.sh", None),
    "Notification": ("voxpane-notification.sh", None),
    "SessionStart": ("voxpane-session-start.sh", None),
    "SessionEnd": ("voxpane-session-end.sh", None),
}


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _source_hooks_dir() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [here.parents[2] / "hooks", here.parent / "data" / "hooks"]
    return next((c for c in candidates if (c / "voxpane-stop.sh").is_file()), None)


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

    dest = hooks_dest or (paths.config_dir() / "hooks")
    paths.ensure(dest)
    for script, _ in _SCRIPTS.values():
        shutil.copy2(source / script, dest / script)
        (dest / script).chmod(0o755)

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
        for event, (script, matcher) in _SCRIPTS.items()
        if _ensure_hook(hooks, event, str(dest / script), matcher)
    ]

    paths.ensure(settings.parent)
    settings.write_text(json.dumps(data, indent=2) + "\n")
    return {"settings": settings, "backup": backup, "added": added, "hooks_dir": dest}
