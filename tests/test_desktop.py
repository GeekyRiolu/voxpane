"""Tests for the desktop-backend abstraction (focus / typing / clipboard)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from voxpane import desktop

_ENV_VARS = ("HYPRLAND_INSTANCE_SIGNATURE", "SWAYSOCK", "WAYLAND_DISPLAY",
             "DISPLAY", "XDG_SESSION_TYPE")


# --------------------------------------------------------------- detection

@pytest.mark.parametrize("env,expected", [
    ({"HYPRLAND_INSTANCE_SIGNATURE": "sig"}, desktop.HYPRLAND),
    ({"SWAYSOCK": "/run/sway.sock"}, desktop.SWAY),
    ({"WAYLAND_DISPLAY": "wayland-0"}, desktop.WAYLAND),
    ({"DISPLAY": ":0"}, desktop.X11),
    ({"XDG_SESSION_TYPE": "x11"}, desktop.X11),
])
def test_detect_backend_from_env(monkeypatch, env, expected):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert desktop.detect_backend() == expected


def test_backend_config_override(monkeypatch):
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "sig")  # detection would say hyprland
    assert desktop.backend({"desktop": {"backend": "x11"}}) == desktop.X11  # override wins
    assert desktop.backend({"desktop": {"backend": "auto"}}) == desktop.HYPRLAND  # -> detect
    assert desktop.backend({"desktop": {"backend": "nope"}}) == desktop.HYPRLAND  # -> detect
    assert desktop.backend(None) == desktop.HYPRLAND


# --------------------------------------------------------------- active_window

def test_hyprland_active_parses_json(monkeypatch):
    win = {"address": "0xabc", "class": "Alacritty", "title": "claude"}
    monkeypatch.setattr(desktop, "_run", lambda cmd, timeout=2.0: json.dumps(win))
    assert desktop.active_window({"desktop": {"backend": "hyprland"}}) == {
        "class": "Alacritty", "title": "claude", "id": "0xabc"}


def test_sway_active_walks_tree_to_focused(monkeypatch):
    tree = {"type": "root", "nodes": [
        {"type": "output", "nodes": [
            {"type": "workspace", "nodes": [
                {"type": "con", "id": 42, "focused": True, "name": "claude - nvim",
                 "app_id": "Alacritty", "window_properties": {}},
                {"type": "con", "id": 7, "focused": False, "name": "other", "app_id": "firefox"},
            ]},
        ]},
    ]}
    monkeypatch.setattr(desktop, "_run", lambda cmd, timeout=2.0: json.dumps(tree))
    assert desktop.active_window({"desktop": {"backend": "sway"}}) == {
        "class": "Alacritty", "title": "claude - nvim", "id": "42"}


def test_x11_active_uses_xdotool_and_xprop(monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, timeout=2.0):
        if cmd[:2] == ["xdotool", "getactivewindow"]:
            return "12345\n"
        if cmd[:2] == ["xdotool", "getwindowname"]:
            return "claude - vim\n"
        if cmd[0] == "xprop":
            return 'WM_CLASS(STRING) = "alacritty", "Alacritty"\n'
        return None

    monkeypatch.setattr(desktop, "_run", fake_run)
    assert desktop.active_window({"desktop": {"backend": "x11"}}) == {
        "class": "Alacritty", "title": "claude - vim", "id": "12345"}


def test_generic_wayland_has_no_focus():
    assert desktop.active_window({"desktop": {"backend": "wayland"}}) is None


# --------------------------------------------------------------- typing

def test_paste_uses_wtype_on_wayland(monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which",
                        lambda name: "/usr/bin/wtype" if name == "wtype" else None)
    runs = []
    monkeypatch.setattr(desktop.subprocess, "run", lambda cmd, **k: runs.append(cmd))
    ok = desktop.paste_and_submit({"desktop": {"backend": "hyprland"}}, submit=True)
    assert ok and runs[0][0] == "wtype" and runs[-1] == ["wtype", "-k", "Return"]


def test_paste_uses_xdotool_on_x11(monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which",
                        lambda name: "/usr/bin/xdotool" if name == "xdotool" else None)
    runs = []
    monkeypatch.setattr(desktop.subprocess, "run", lambda cmd, **k: runs.append(cmd))
    ok = desktop.paste_and_submit({"desktop": {"backend": "x11"}})
    assert ok and runs[0] == ["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"]


def test_paste_returns_false_without_a_tool(monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    assert desktop.paste_and_submit({"desktop": {"backend": "hyprland"}}) is False


# --------------------------------------------------------------- clipboard

def test_clipboard_uses_wl_copy_on_wayland(monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which",
                        lambda name: "/usr/bin/wl-copy" if name == "wl-copy" else None)
    seen = {}
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda argv, **k: seen.update(argv=argv, input=k.get("input")))
    desktop.clipboard_copy("hi", {"desktop": {"backend": "hyprland"}})
    assert seen["argv"] == ["wl-copy"] and seen["input"] == "hi"


def test_clipboard_prefers_xclip_on_x11(monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")  # all present
    seen = {}
    monkeypatch.setattr(desktop.subprocess, "run", lambda argv, **k: seen.update(argv=argv))
    desktop.clipboard_copy("hi", {"desktop": {"backend": "x11"}})
    assert seen["argv"] == ["xclip", "-selection", "clipboard"]


def test_clipboard_raises_without_a_tool(monkeypatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="no clipboard tool"):
        desktop.clipboard_copy("x", {"desktop": {"backend": "hyprland"}})


# --------------------------------------------------------------- overlay

def test_overlay_supported_only_on_wlroots():
    assert desktop.overlay_supported({"desktop": {"backend": "hyprland"}}) is True
    assert desktop.overlay_supported({"desktop": {"backend": "sway"}}) is True
    assert desktop.overlay_supported({"desktop": {"backend": "x11"}}) is False
    assert desktop.overlay_supported({"desktop": {"backend": "wayland"}}) is False
    assert desktop.overlay_supported({"desktop": {"backend": "windows"}}) is False


# --------------------------------------------------------------- windows

_WIN = {"desktop": {"backend": "windows"}}


def test_detect_backend_windows_wins_first(monkeypatch):
    monkeypatch.setattr(desktop.osutil, "IS_WINDOWS", True)
    assert desktop.detect_backend() == desktop.WINDOWS


def test_windows_is_a_valid_config_backend():
    assert desktop.backend(_WIN) == desktop.WINDOWS  # accepted (in _KNOWN)


def test_active_window_dispatches_to_windows_backend(monkeypatch):
    fake = {"class": "WindowsTerminal.exe", "title": "claude", "id": "12345"}
    monkeypatch.setattr(desktop, "_windows_active", lambda: fake)
    assert desktop.active_window(_WIN) == fake


def test_type_tool_unknown_backend_returns_none(monkeypatch):
    # Windows has no shell typing tool; the hardened .get must not KeyError.
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert desktop._type_tool(_WIN) is None


def test_windows_clipboard_uses_powershell_set_clipboard(monkeypatch):
    monkeypatch.setattr(desktop, "_powershell", lambda: "pwsh")
    seen = {}
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda argv, **k: seen.update(argv=argv, input=k.get("input")))
    desktop.clipboard_copy("héllo", _WIN)
    assert seen["argv"][0] == "pwsh" and "Set-Clipboard" in seen["argv"][-1]
    assert seen["input"] == "héllo"


def test_windows_clipboard_falls_back_to_clip(monkeypatch):
    monkeypatch.setattr(desktop, "_powershell", lambda: None)
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/c/clip" if name == "clip" else None)
    seen = {}
    monkeypatch.setattr(desktop.subprocess, "run", lambda argv, **k: seen.update(argv=argv))
    desktop.clipboard_copy("hi", _WIN)
    assert seen["argv"] == ["clip"]


def test_windows_clipboard_raises_without_a_tool(monkeypatch):
    monkeypatch.setattr(desktop, "_powershell", lambda: None)
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="no clipboard tool"):
        desktop.clipboard_copy("x", _WIN)


def test_windows_paste_sends_ctrl_v_and_enter(monkeypatch):
    monkeypatch.setattr(desktop, "_powershell", lambda: "powershell")
    runs = []
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda argv, **k: runs.append(argv) or SimpleNamespace(returncode=0))
    assert desktop.paste_and_submit(_WIN, submit=True) is True
    assert "SendKeys" in runs[0][-1] and "^v{ENTER}" in runs[0][-1]


def test_windows_paste_without_submit_omits_enter(monkeypatch):
    monkeypatch.setattr(desktop, "_powershell", lambda: "powershell")
    runs = []
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda argv, **k: runs.append(argv) or SimpleNamespace(returncode=0))
    desktop.paste_and_submit(_WIN)
    assert "^v" in runs[0][-1] and "{ENTER}" not in runs[0][-1]


def test_windows_paste_returns_false_without_powershell(monkeypatch):
    monkeypatch.setattr(desktop, "_powershell", lambda: None)
    assert desktop.paste_and_submit(_WIN) is False
