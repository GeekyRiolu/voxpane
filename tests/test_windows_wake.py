"""Windows wake-word terminal spawn (WS3): terminal detection + launch argv.

The POSIX `sh -lc "cd … && …"` has no equivalent on Windows, so the launch argv is
built per terminal (wt / cmd / pwsh). Exercised on Linux by forcing osutil.IS_WINDOWS.
"""

from __future__ import annotations

from types import SimpleNamespace

from voxpane import cli, listen, osutil


def test_detect_terminal_windows_prefers_wt(monkeypatch):
    monkeypatch.setattr(listen.osutil, "IS_WINDOWS", True)
    monkeypatch.setattr(listen.shutil, "which",
                        lambda t: f"C:/{t}.exe" if t in ("wt", "cmd") else None)
    assert listen._detect_terminal({"listen": {}}) == ["wt"]


def test_detect_terminal_windows_falls_back_to_cmd(monkeypatch):
    monkeypatch.setattr(listen.osutil, "IS_WINDOWS", True)
    monkeypatch.setattr(listen.shutil, "which", lambda t: "C:/cmd.exe" if t == "cmd" else None)
    assert listen._detect_terminal({"listen": {}}) == ["cmd"]


def test_wake_argv_windows_terminal_uses_working_dir(monkeypatch):
    monkeypatch.setattr(listen.osutil, "IS_WINDOWS", True)
    argv = listen._wake_argv(["wt"], r"C:\Users\me\repo", "claude --model opus")
    assert argv[:3] == ["wt", "-d", r"C:\Users\me\repo"]
    assert "claude" in argv and "--model" in argv


def test_wake_argv_windows_cmd_chains_cd(monkeypatch):
    monkeypatch.setattr(listen.osutil, "IS_WINDOWS", True)
    argv = listen._wake_argv(["cmd"], r"C:\repo", "claude")
    assert argv[0] == "cmd" and argv[1] == "/c"
    assert "cd /d" in argv[2] and "claude" in argv[2]


def test_wake_argv_windows_powershell_sets_location(monkeypatch):
    monkeypatch.setattr(listen.osutil, "IS_WINDOWS", True)
    argv = listen._wake_argv(["pwsh"], r"C:\repo", "claude")
    assert "-Command" in argv and "Set-Location" in argv[-1] and "claude" in argv[-1]


def test_wake_argv_posix_uses_sh_lc(monkeypatch):
    monkeypatch.setattr(listen.osutil, "IS_WINDOWS", False)
    argv = listen._wake_argv(["alacritty", "-e"], "/home/x/repo", "claude")
    assert argv[:4] == ["alacritty", "-e", "sh", "-lc"]
    assert "cd" in argv[-1] and "claude" in argv[-1]


def test_install_listener_windows_registers_scheduled_task(monkeypatch, tmp_path):
    import shutil
    import subprocess

    monkeypatch.setattr(osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(shutil, "which", lambda n: f"C:/{n}.exe")
    calls = []
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **k: calls.append(argv) or SimpleNamespace(
                            returncode=0, stdout="", stderr=""))

    assert cli._install_listener_windows() == 0
    assert any(c[:2] == ["schtasks", "/Create"] for c in calls)
    assert any(c[:2] == ["schtasks", "/Run"] for c in calls)
