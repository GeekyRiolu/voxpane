"""Tests for the desktop-backend abstraction (focus / typing / clipboard)."""

from __future__ import annotations

import json

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
