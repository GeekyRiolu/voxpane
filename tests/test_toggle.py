"""Tests for `voxpane toggle` dispatch (M2). Subprocess-free."""

from __future__ import annotations

from pathlib import Path

import pytest

from voxpane import cli, deliver, notify, recorder, transcriber


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # Keep all state and config under the temp dir; silence notifications.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(notify, "notify", lambda *a, **k: None)


def test_toggle_starts_when_idle(monkeypatch):
    started = {}
    monkeypatch.setattr(recorder, "is_recording", lambda: False)

    def fake_start(cfg):
        started["called"] = True
        return Path("/tmp/vp-x.wav")

    monkeypatch.setattr(recorder, "start", fake_start)

    assert cli.main(["toggle"]) == 0
    assert started["called"]


def test_toggle_stops_and_copies_when_recording(monkeypatch, tmp_path):
    wav = tmp_path / "vp.wav"
    wav.write_bytes(b"RIFF____WAVE")
    copied = {}

    def fake_deliver(text, cfg, submit=False):
        copied["text"] = text
        return "copied to clipboard"

    monkeypatch.setattr(recorder, "is_recording", lambda: True)
    monkeypatch.setattr(recorder, "stop", lambda: wav)
    monkeypatch.setattr(transcriber, "transcribe_file", lambda w, c: "hello world")
    monkeypatch.setattr(deliver, "deliver", fake_deliver)

    assert cli.main(["toggle"]) == 0
    assert copied["text"] == "hello world"


def test_preview_collapses_and_caps():
    long = "word " * 60
    out = cli._preview(long, max_chars=40)
    assert len(out) <= 40
    assert "\n" not in out
    assert out.endswith("…")


def test_status_reports_recording(monkeypatch, capsys):
    import json

    monkeypatch.setattr(recorder, "is_recording", lambda: True)
    assert cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["class"] == "recording"
