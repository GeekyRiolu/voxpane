"""Tests for the speaker backends and fallback chain (M8)."""

from __future__ import annotations

import pytest

from voxpane import config, notify, speakers
from voxpane.speakers import alexa, bluetooth


@pytest.fixture(autouse=True)
def _runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))


def _cfg(backends=("alexa", "bluetooth", "notify")):
    cfg = config.defaults()
    cfg["speak"]["backends"] = list(backends)
    return cfg


def test_get_backend_unknown_raises():
    with pytest.raises(ValueError, match="unknown speaker"):
        speakers.get_backend("nope", config.defaults())


def test_prefers_alexa_when_available(monkeypatch):
    spoke = {}
    monkeypatch.setattr(alexa.AlexaSpeaker, "available", lambda self: True)
    monkeypatch.setattr(alexa.AlexaSpeaker, "speak", lambda self, t: spoke.setdefault("via", t))
    assert speakers.speak_with_fallback("hi", _cfg()) == "alexa"
    assert spoke["via"] == "hi"


def test_falls_through_alexa_to_bluetooth(monkeypatch):
    spoke = {}

    def bt_speak(self, text):
        spoke["via"] = text

    monkeypatch.setattr(alexa.AlexaSpeaker, "available", lambda self: False)  # network down
    monkeypatch.setattr(bluetooth.BluetoothSpeaker, "available", lambda self: True)
    monkeypatch.setattr(bluetooth.BluetoothSpeaker, "speak", bt_speak)
    assert speakers.speak_with_fallback("hi", _cfg()) == "bluetooth"
    assert spoke["via"] == "hi"


def test_falls_through_to_notify_when_all_audible_fail(monkeypatch):
    def raise_speaker(self, text):
        raise speakers.SpeakerError("network down")

    monkeypatch.setattr(alexa.AlexaSpeaker, "available", lambda self: True)
    monkeypatch.setattr(alexa.AlexaSpeaker, "speak", raise_speaker)  # available but errors
    monkeypatch.setattr(bluetooth.BluetoothSpeaker, "available", lambda self: False)
    notified = {}
    monkeypatch.setattr(notify, "notify", lambda *a, **k: notified.setdefault("hit", True))

    assert speakers.speak_with_fallback("hi", _cfg()) == "notify"
    assert notified["hit"]


def test_notify_is_the_floor_even_if_unlisted(monkeypatch):
    monkeypatch.setattr(alexa.AlexaSpeaker, "available", lambda self: False)
    monkeypatch.setattr(bluetooth.BluetoothSpeaker, "available", lambda self: False)
    notified = {}
    monkeypatch.setattr(notify, "notify", lambda *a, **k: notified.setdefault("hit", True))
    # backends without "notify" — the floor still guarantees delivery
    assert speakers.speak_with_fallback("hi", _cfg(backends=["alexa", "bluetooth"])) == "notify"
    assert notified["hit"]


def test_notify_backend_never_raises(monkeypatch):
    monkeypatch.setattr(notify, "notify", lambda *a, **k: None)
    speakers.get_backend("notify", config.defaults()).speak("x")  # must not raise
