"""Tests for clipboard delivery (M1). Subprocess mocked."""

from __future__ import annotations

import pytest

from voxpane import deliver


def test_to_clipboard_pipes_text_to_wl_copy(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["input"] = kwargs.get("input")

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(deliver.subprocess, "run", fake_run)
    monkeypatch.setattr(deliver.shutil, "which", lambda name: "/usr/bin/wl-copy")

    deliver.to_clipboard("hello world")

    assert seen["cmd"][0] == "wl-copy"
    assert seen["input"] == "hello world"


def test_to_clipboard_raises_without_wl_copy(monkeypatch):
    monkeypatch.setattr(deliver.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="wl-copy not found"):
        deliver.to_clipboard("x")
