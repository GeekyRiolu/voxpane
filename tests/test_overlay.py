"""Tests for the on-screen overlay state."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from voxpane import overlay, paths


@pytest.fixture(autouse=True)
def _runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))


def test_set_and_read_state():
    overlay.set_state("listening", "hello world")
    state = overlay.read_state()
    assert state["state"] == "listening"
    assert state["text"] == "hello world"


def test_read_idle_when_unset():
    assert overlay.read_state() == {"state": "idle", "text": ""}


def test_stale_state_reads_idle():
    paths.ensure(paths.runtime_dir())
    paths.overlay_state_file().write_text(
        json.dumps({"state": "listening", "text": "x", "ts": time.time() - 100})
    )
    assert overlay.read_state()["state"] == "idle"  # too old


def test_clear():
    overlay.set_state("thinking", "y")
    overlay.clear()
    assert overlay.read_state()["state"] == "idle"


def test_sprite_path_returns_shipped_svg():
    path = overlay.sprite_path("listening")
    assert path.endswith("listening.svg")
    assert Path(path).is_file()


def test_sprite_path_prefers_user_override(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    pet_dir = tmp_path / "voxpane" / "pet"
    pet_dir.mkdir(parents=True)
    (pet_dir / "listening.png").write_bytes(b"\x89PNG")
    assert overlay.sprite_path("listening") == str(pet_dir / "listening.png")


def test_sprite_path_falls_back_to_idle(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))  # no overrides
    assert overlay.sprite_path("nonsense").endswith("idle.svg")
