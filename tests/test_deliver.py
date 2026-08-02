"""Tests for delivery backends — clipboard (M1), tmux + focus (M3)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from voxpane import config, deliver


def _cfg(mode, **delivery):
    cfg = config.defaults()
    cfg["delivery"]["mode"] = mode
    cfg["delivery"].update(delivery)
    return cfg


def test_to_clipboard_pipes_text_to_wl_copy(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["input"] = kwargs.get("input")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(deliver.subprocess, "run", fake_run)
    monkeypatch.setattr(deliver.shutil, "which", lambda name: "/usr/bin/wl-copy")

    deliver.to_clipboard("hello world")
    assert seen["cmd"][0] == "wl-copy"
    assert seen["input"] == "hello world"


def test_to_clipboard_raises_without_wl_copy(monkeypatch):
    monkeypatch.setattr(deliver.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="wl-copy not found"):
        deliver.to_clipboard("x")


def test_clipboard_mode(monkeypatch):
    called = {}
    monkeypatch.setattr(deliver, "to_clipboard", lambda t: called.setdefault("t", t))
    status = deliver.deliver("hi", _cfg("clipboard"))
    assert called["t"] == "hi"
    assert "clipboard" in status


def test_tmux_mode_sends_literal_without_enter(monkeypatch):
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return SimpleNamespace(returncode=0, stdout="%1")

    monkeypatch.setattr(deliver.subprocess, "run", fake_run)
    monkeypatch.setattr(deliver.shutil, "which", lambda name: f"/usr/bin/{name}")

    status = deliver.deliver("hello", _cfg("tmux", tmux_target="claude:0.0"), submit=False)

    send = [c for c in runs if c[:2] == ["tmux", "send-keys"]]
    assert any("-l" in c and "--" in c and "hello" in c for c in send)
    assert not any(c[-1] == "Enter" for c in send)  # never submits unasked
    assert "claude:0.0" in status


def test_tmux_mode_submits_enter_when_asked(monkeypatch):
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return SimpleNamespace(returncode=0, stdout="%1")

    monkeypatch.setattr(deliver.subprocess, "run", fake_run)
    monkeypatch.setattr(deliver.shutil, "which", lambda name: f"/usr/bin/{name}")

    deliver.deliver("hello", _cfg("tmux"), submit=True)
    assert any(c[-1] == "Enter" for c in runs)


def test_tmux_pane_gone_falls_back_to_clipboard(monkeypatch):
    monkeypatch.setattr(
        deliver.subprocess, "run", lambda cmd, **k: SimpleNamespace(returncode=1, stdout="")
    )
    monkeypatch.setattr(deliver.shutil, "which", lambda name: f"/usr/bin/{name}")
    fell_back = {}
    monkeypatch.setattr(deliver, "to_clipboard", lambda t: fell_back.setdefault("t", t))

    status = deliver.deliver("hello", _cfg("tmux", tmux_target="claude:0.0"))
    assert fell_back["t"] == "hello"
    assert "gone" in status


def test_focus_mode_pastes_with_wtype(monkeypatch):
    runs = []
    monkeypatch.setattr(deliver, "to_clipboard", lambda t: None)
    monkeypatch.setattr(deliver.time, "sleep", lambda s: None)

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(deliver.subprocess, "run", fake_run)
    monkeypatch.setattr(deliver.shutil, "which", lambda name: f"/usr/bin/{name}")

    status = deliver.deliver("hello", _cfg("focus"))
    assert any(c[0] == "wtype" for c in runs)
    assert "focused" in status
