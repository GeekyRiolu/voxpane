"""macOS wake-word terminal spawn + launchd service (M3).

Exercised on Linux by forcing osutil.IS_MACOS and mocking subprocess/filesystem.
"""

from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

from voxpane import cli, listen, osutil


def test_detect_terminal_macos_uses_osascript(monkeypatch):
    monkeypatch.setattr(listen.osutil, "IS_MACOS", True)
    monkeypatch.setattr(listen.shutil, "which",
                        lambda t: "/usr/bin/osascript" if t == "osascript" else None)
    assert listen._detect_terminal({"listen": {}}) == ["osascript"]


def test_wake_argv_macos_drives_terminal_app(monkeypatch):
    monkeypatch.setattr(listen.osutil, "IS_MACOS", True)
    argv = listen._wake_argv(["osascript"], "/Users/me/repo", "claude --model opus")
    assert argv[0] == "osascript" and argv[1] == "-e"
    script = argv[2]
    for token in ('tell application "Terminal"', "do script", "/Users/me/repo", "claude"):
        assert token in script


def test_install_listener_macos_writes_launchagent(monkeypatch, tmp_path):
    monkeypatch.setattr(osutil, "IS_WINDOWS", False)
    monkeypatch.setattr(osutil, "IS_MACOS", True)
    monkeypatch.setenv("HOME", str(tmp_path))  # Path.home() -> tmp; LaunchAgents under it
    monkeypatch.setattr(shutil, "which", lambda n: f"/usr/bin/{n}")
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **k: calls.append(argv) or SimpleNamespace(returncode=0))

    assert cli._install_listener_macos() == 0
    plist = tmp_path / "Library" / "LaunchAgents" / "com.voxpane.listen.plist"
    assert plist.exists()
    text = plist.read_text()
    assert "<string>listen</string>" in text and "<string>--run</string>" in text
    assert any(c[:2] == ["launchctl", "load"] for c in calls)
