"""Tests for `voxpane doctor` (M0)."""

from __future__ import annotations

import copy

from voxpane import config, doctor


def _cfg():
    return copy.deepcopy(config.defaults())


def test_run_checks_returns_checks():
    checks = doctor.run_checks(_cfg())
    assert checks
    assert all(isinstance(c, doctor.Check) for c in checks)


def test_stt_fails_without_daemon_or_whisper(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))  # no daemon socket
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)  # no whisper-cli
    cfg = _cfg()
    cfg["whisper"]["model"] = str(tmp_path / "nope.bin")
    stt = next(c for c in doctor.run_checks(cfg) if c.name == "speech-to-text")
    assert not stt.ok and stt.hint


def test_stt_ok_when_daemon_socket_present(tmp_path, monkeypatch):
    import socket

    from voxpane import paths

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    paths.ensure(paths.runtime_dir())
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(paths.socket_path()))
    server.listen(1)
    try:
        stt = next(c for c in doctor.run_checks(_cfg()) if c.name == "speech-to-text")
        assert stt.ok and "daemon" in stt.detail
    finally:
        server.close()


def test_render_marks_pass_and_fail():
    ok = doctor.Check("thing", True, "found")
    bad = doctor.Check("other", False, "missing", "install it")
    rendered = doctor.render([ok, bad])
    assert "✓" in rendered and "✗" in rendered
    assert "install it" in rendered


def test_main_returns_int():
    out = []
    rc = doctor.main(_cfg(), printer=out.append)
    assert isinstance(rc, int)
    assert any("voxpane doctor" in line for line in out)


# ------------------------------------------------------- backend awareness

def test_backend_reported_and_marked_experimental():
    cfg = _cfg()
    cfg["desktop"]["backend"] = "sway"
    desk = next(c for c in doctor.run_checks(cfg) if c.name == "desktop")
    assert desk.ok and "sway" in desk.detail and "experimental" in desk.detail


def test_x11_needs_xdotool_and_xclip_not_wayland_tools():
    names = {n for n, _h, _s in doctor._desktop_binaries(_cfg(), "x11")}
    assert "xdotool" in names and "xclip" in names
    assert "wl-copy" not in names and "wtype" not in names


def test_generic_wayland_uses_ydotool_and_has_no_focus_reader():
    names = {n for n, _h, _s in doctor._desktop_binaries(_cfg(), "wayland")}
    assert "ydotool" in names and "wl-copy" in names
    assert "hyprctl" not in names and "swaymsg" not in names  # no focus CLI there


def test_typing_tool_hard_only_in_focus_mode():
    focus_cfg = _cfg()
    focus_cfg["delivery"]["mode"] = "focus"
    soft_by_name = {n: s for n, _h, s in doctor._desktop_binaries(focus_cfg, "hyprland")}
    assert soft_by_name["wtype"] is False          # required for focus delivery
    tmux_cfg = _cfg()  # default delivery mode is tmux
    soft_by_name = {n: s for n, _h, s in doctor._desktop_binaries(tmux_cfg, "hyprland")}
    assert soft_by_name["wtype"] is True           # advisory otherwise


def test_install_hint_follows_the_package_manager(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which",
                        lambda name: "/usr/bin/apt" if name == "apt" else None)
    assert doctor._install_hint("wl-copy") == "sudo apt install wl-clipboard"
    assert doctor._install_hint("notify-send") == "sudo apt install libnotify-bin"


def test_install_hint_is_neutral_without_a_known_manager(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    assert doctor._install_hint("wl-copy") == "install wl-clipboard"


# ------------------------------------------------------- windows

def _win(cfg):
    cfg["desktop"]["backend"] = "windows"
    return cfg


def test_windows_backend_check_reports_no_pet(monkeypatch):
    monkeypatch.setattr(doctor.osutil, "IS_WINDOWS", True)
    desk = next(c for c in doctor.run_checks(_win(_cfg())) if c.name == "desktop")
    assert "windows" in desk.detail and "experimental" in desk.detail
    assert "Linux/wlroots only" in desk.detail


def test_windows_desktop_binary_is_powershell():
    rows = doctor._desktop_binaries(_win(_cfg()), "windows")
    assert [n for n, _h, _s in rows] == ["powershell"]


def test_windows_audio_check_wants_sounddevice(monkeypatch):
    monkeypatch.setattr(doctor.osutil, "IS_WINDOWS", True)
    check = doctor._audio_input_check()
    # sounddevice isn't installed in this Linux test env → fails with a pip hint.
    assert check.name == "audio capture"
    assert check.ok is False and "voxpane[windows]" in check.hint


def test_windows_install_hint_uses_winget(monkeypatch):
    monkeypatch.setattr(doctor.osutil, "IS_WINDOWS", True)
    monkeypatch.setattr(doctor.shutil, "which",
                        lambda name: "C:/winget.exe" if name == "winget" else None)
    assert doctor._install_hint("whisper-cli") == "winget install whisper-cli"


def test_windows_run_checks_skips_linux_only(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor.osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # isolate runtime-dir writes
    names = {c.name for c in doctor.run_checks(_win(_cfg()))}
    assert "desktop" in names and "audio capture" in names
    for linux_only in ("notify-send", "jq", "playerctl", "audio source", "alexa", "bluez sink"):
        assert linux_only not in names
