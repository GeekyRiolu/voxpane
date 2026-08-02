"""Tests for the hands-free listen mode's pure logic (VAD endpointer)."""

from __future__ import annotations

from voxpane import config, listen


def _feed(endpointer, speech_pattern):
    """Feed a sequence of is_speech flags; return emitted utterance frame-counts."""
    emitted = []
    for i, is_speech in enumerate(speech_pattern):
        utterance = endpointer.process(bytes([i % 256, 0]), is_speech)  # 2-byte dummy frame
        if utterance is not None:
            emitted.append(len(utterance) // 2)
    return emitted


def test_emits_utterance_after_trailing_silence():
    # 20ms frames, 100ms endpoint silence (=5 frames), 40ms min speech, 2s max
    ep = listen.Endpointer(frame_ms=20, silence_ms=100, min_speech_ms=40, max_ms=2000)
    emitted = _feed(ep, [True] * 10 + [False] * 6)
    assert emitted == [15]  # 10 voiced + 5 silence frames, emitted on the 5th


def test_drops_utterance_below_min_speech():
    ep = listen.Endpointer(frame_ms=20, silence_ms=100, min_speech_ms=200, max_ms=2000)
    emitted = _feed(ep, [True] * 3 + [False] * 6)  # only 3 voiced, need 10
    assert emitted == []


def test_caps_a_never_ending_utterance():
    ep = listen.Endpointer(frame_ms=20, silence_ms=100_000, min_speech_ms=20, max_ms=200)
    emitted = _feed(ep, [True] * 15)  # never silent → capped at 10 frames (200ms)
    assert emitted == [10]


def test_ignores_leading_silence():
    ep = listen.Endpointer(frame_ms=20, silence_ms=100, min_speech_ms=20, max_ms=2000)
    emitted = _feed(ep, [False] * 20 + [True] * 4 + [False] * 6)
    assert emitted == [9]  # 4 voiced + 5 silence; leading silence ignored


def test_stop_word_detection():
    cfg = config.defaults()
    assert listen.is_stop_word("stop", cfg)
    assert listen.is_stop_word("Stop it.", cfg)
    assert not listen.is_stop_word("stop the server", cfg)


def test_listen_defaults_present():
    listen_cfg = config.defaults()["listen"]
    assert listen_cfg["auto_submit"] is True
    assert listen_cfg["endpoint_silence_ms"] == 1500


def test_session_refcount_starts_once_stops_last(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    calls = {"spawn": 0, "stop": 0}

    def spawn():
        calls["spawn"] += 1

    def stop():
        calls["stop"] += 1

    monkeypatch.setattr(listen, "_spawn_listener", spawn)
    monkeypatch.setattr(listen, "is_listening", lambda: calls["spawn"] > 0)
    monkeypatch.setattr(listen, "stop", stop)
    cfg = config.defaults()

    listen.ensure("a", cfg)
    listen.ensure("b", cfg)  # second session — listener already up
    assert calls["spawn"] == 1

    listen.release("a")  # still one session left
    assert calls["stop"] == 0
    listen.release("b")  # last one — stop
    assert calls["stop"] == 1


def test_ensure_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(listen, "_spawn_listener", lambda: (_ for _ in ()).throw(AssertionError()))
    cfg = config.defaults()
    cfg["listen"]["enabled"] = False
    listen.ensure("a", cfg)  # must not spawn
