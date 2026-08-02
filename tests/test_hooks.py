"""Tests for `voxpane install-hooks` settings.json merging (M6)."""

from __future__ import annotations

import json

from voxpane import hooks


def test_install_into_empty_settings(tmp_path):
    settings = tmp_path / "settings.json"
    dest = tmp_path / "hooks"

    result = hooks.install_hooks(settings=settings, hooks_dest=dest)

    assert set(result["added"]) == {"PostToolUse", "Stop", "Notification"}
    data = json.loads(settings.read_text())
    assert "PostToolUse" in data["hooks"] and "Stop" in data["hooks"]
    assert "Notification" in data["hooks"]
    assert (dest / "voxpane-stop.sh").exists()
    assert (dest / "voxpane-post-tool.sh").stat().st_mode & 0o111  # executable


def test_idempotent_and_backs_up(tmp_path):
    settings = tmp_path / "settings.json"
    dest = tmp_path / "hooks"

    hooks.install_hooks(settings=settings, hooks_dest=dest)
    second = hooks.install_hooks(settings=settings, hooks_dest=dest)

    assert second["added"] == []
    assert second["backup"] and second["backup"].exists()
    data = json.loads(settings.read_text())
    assert len(data["hooks"]["Stop"]) == 1  # not duplicated


def test_preserves_existing_hooks_and_keys(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine.sh"}]}]},
                "model": "opus",
            }
        )
    )

    hooks.install_hooks(settings=settings, hooks_dest=tmp_path / "hooks")

    data = json.loads(settings.read_text())
    commands = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
    assert "mine.sh" in commands  # existing hook untouched
    assert any("voxpane-stop.sh" in c for c in commands)  # ours added
    assert data["model"] == "opus"  # unrelated keys intact
