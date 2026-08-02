"""Tests for `voxpane hush` (stop the Dot mid-sentence)."""

from __future__ import annotations

from voxpane import hush, paths


def test_hush_kills_recorded_play_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    paths.ensure(paths.runtime_dir())
    killed = {}
    monkeypatch.setattr(hush.os, "kill", lambda pid, sig: killed.setdefault("pid", pid))

    paths.play_pid_file().write_text("4242")
    paths.speaking_marker().touch()

    assert hush.hush() is True
    assert killed["pid"] == 4242
    assert not paths.play_pid_file().exists()
    assert not paths.speaking_marker().exists()  # state cleared


def test_hush_noop_when_nothing_playing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    paths.ensure(paths.runtime_dir())
    assert hush.hush() is False
