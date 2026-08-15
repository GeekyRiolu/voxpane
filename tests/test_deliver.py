"""Tests for delivery modes — clipboard (M1), tmux + focus (M3).

The desktop-specific argv (wl-copy / xclip / wtype / xdotool) lives in
tests/test_desktop.py; here we test the delivery-mode logic against a mocked backend.
"""

from __future__ import annotations

from types import SimpleNamespace

from voxpane import config, deliver, desktop


def _cfg(mode, **delivery):
    cfg = config.defaults()
    cfg["delivery"]["mode"] = mode
    cfg["delivery"].update(delivery)
    return cfg


def _record_run(runs):
    def run(cmd, **kwargs):
        runs.append(cmd)
        return SimpleNamespace(returncode=0, stdout="%1")
    return run


def test_to_clipboard_delegates_to_desktop(monkeypatch):
    seen = {}
    monkeypatch.setattr(desktop, "clipboard_copy",
                        lambda text, cfg=None: seen.update(text=text))
    deliver.to_clipboard("hello world")
    assert seen["text"] == "hello world"


def test_clipboard_mode(monkeypatch):
    called = {}
    monkeypatch.setattr(deliver, "to_clipboard", lambda t, cfg=None: called.setdefault("t", t))
    status = deliver.deliver("hi", _cfg("clipboard"))
    assert called["t"] == "hi" and "clipboard" in status


def test_tmux_mode_sends_literal_without_enter(monkeypatch):
    runs = []
    monkeypatch.setattr(deliver.subprocess, "run", _record_run(runs))
    monkeypatch.setattr(deliver.shutil, "which", lambda name: f"/usr/bin/{name}")
    status = deliver.deliver("hello", _cfg("tmux", tmux_target="claude:0.0"), submit=False)
    send = [c for c in runs if c[:2] == ["tmux", "send-keys"]]
    assert any("-l" in c and "--" in c and "hello" in c for c in send)
    assert not any(c[-1] == "Enter" for c in send)  # never submits unasked
    assert "claude:0.0" in status


def test_tmux_mode_submits_enter_when_asked(monkeypatch):
    runs = []
    monkeypatch.setattr(deliver.subprocess, "run", _record_run(runs))
    monkeypatch.setattr(deliver.shutil, "which", lambda name: f"/usr/bin/{name}")
    deliver.deliver("hello", _cfg("tmux"), submit=True)
    assert any(c[-1] == "Enter" for c in runs)


def test_tmux_pane_gone_falls_back_to_clipboard(monkeypatch):
    monkeypatch.setattr(deliver.subprocess, "run",
                        lambda cmd, **k: SimpleNamespace(returncode=1, stdout=""))
    monkeypatch.setattr(deliver.shutil, "which", lambda name: f"/usr/bin/{name}")
    fell_back = {}
    monkeypatch.setattr(deliver, "to_clipboard", lambda t, cfg=None: fell_back.setdefault("t", t))
    status = deliver.deliver("hello", _cfg("tmux", tmux_target="claude:0.0"))
    assert fell_back["t"] == "hello" and "gone" in status


def test_focus_mode_pastes_via_desktop(monkeypatch):
    monkeypatch.setattr(deliver, "to_clipboard", lambda t, cfg=None: None)
    monkeypatch.setattr(deliver.time, "sleep", lambda s: None)
    calls = {}
    monkeypatch.setattr(desktop, "paste_and_submit",
                        lambda cfg=None, *, submit=False: calls.update(submit=submit) or True)
    status = deliver.deliver("hello", _cfg("focus"), submit=True)
    assert calls["submit"] is True and "focused" in status


def test_focus_mode_falls_back_when_no_typer(monkeypatch):
    monkeypatch.setattr(deliver, "to_clipboard", lambda t, cfg=None: None)
    monkeypatch.setattr(deliver.time, "sleep", lambda s: None)
    monkeypatch.setattr(desktop, "paste_and_submit", lambda cfg=None, *, submit=False: False)
    status = deliver.deliver("hello", _cfg("focus"))
    assert "clipboard" in status  # no typing tool -> stays on the clipboard


def test_tmux_mode_without_tmux_falls_back_to_clipboard(monkeypatch):
    # e.g. Windows: the default tmux mode has no tmux — degrade to the clipboard.
    monkeypatch.setattr(deliver.shutil, "which", lambda name: None)
    copied = {}
    monkeypatch.setattr(deliver, "to_clipboard", lambda t, cfg=None: copied.setdefault("t", t))
    status = deliver.deliver("hello", _cfg("tmux"))
    assert copied["t"] == "hello" and "not installed" in status
