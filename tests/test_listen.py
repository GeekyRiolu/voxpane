"""Tests for the hands-free listen mode's pure logic (VAD endpointer)."""

from __future__ import annotations

from types import SimpleNamespace

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


# --- focus gate: only listen while the Claude window is focused ---

def test_focus_ok_true_when_disabled():
    cfg = config.defaults()
    cfg["listen"]["focus_only"] = False
    assert listen.focus_ok(cfg) is True


def test_focus_ok_true_for_the_captured_window(monkeypatch):
    win = {"address": "0xabc", "class": "foot", "title": "claude"}
    monkeypatch.setattr(listen, "_active_window", lambda: win)
    monkeypatch.setattr(listen, "_load_windows", lambda: {"s1": win})
    assert listen.focus_ok(config.defaults()) is True


def test_focus_ok_false_for_a_different_window(monkeypatch):
    other = {"address": "0xff", "class": "firefox", "title": "YouTube"}
    captured = {"address": "0xabc", "class": "foot", "title": ""}
    monkeypatch.setattr(listen, "_active_window", lambda: other)
    monkeypatch.setattr(listen, "_load_windows", lambda: {"s1": captured})
    assert listen.focus_ok(config.defaults()) is False  # ignores YouTube


def test_focus_ok_true_when_nothing_captured(monkeypatch):
    win = {"address": "0xabc", "class": "foot", "title": ""}
    monkeypatch.setattr(listen, "_active_window", lambda: win)
    monkeypatch.setattr(listen, "_load_windows", lambda: {})
    assert listen.focus_ok(config.defaults()) is True  # don't block if unset


def test_focus_ok_true_when_undetectable(monkeypatch):
    monkeypatch.setattr(listen, "_active_window", lambda: None)  # no hyprctl
    assert listen.focus_ok(config.defaults()) is True


def test_focus_match_regex_override(monkeypatch):
    cfg = config.defaults()
    cfg["listen"]["focus_match"] = "kitty|foot"
    term = {"address": "0x1", "class": "foot", "title": "x"}
    browser = {"address": "0x2", "class": "firefox", "title": "yt"}
    monkeypatch.setattr(listen, "_active_window", lambda: term)
    assert listen.focus_ok(cfg) is True
    monkeypatch.setattr(listen, "_active_window", lambda: browser)
    assert listen.focus_ok(cfg) is False


# --- playback gate: pause the mic while other apps play audio ---

def test_media_playing_true_when_uncorked(monkeypatch):
    monkeypatch.setattr(listen.shutil, "which", lambda name: "/usr/bin/pactl")
    out = SimpleNamespace(returncode=0, stdout="Sink Input #1\n\tCorked: no\n")
    monkeypatch.setattr(listen.subprocess, "run", lambda *a, **k: out)
    assert listen._media_playing() is True


def test_media_playing_false_when_all_corked(monkeypatch):
    monkeypatch.setattr(listen.shutil, "which", lambda name: "/usr/bin/pactl")
    out = SimpleNamespace(returncode=0, stdout="Sink Input #1\n\tCorked: yes\n")
    monkeypatch.setattr(listen.subprocess, "run", lambda *a, **k: out)
    assert listen._media_playing() is False


def test_media_playing_true_when_sink_running(monkeypatch):
    monkeypatch.setattr(listen.shutil, "which", lambda name: "/usr/bin/pactl")
    out = SimpleNamespace(returncode=0, stdout="Sink #1\n\tState: RUNNING\n")
    monkeypatch.setattr(listen.subprocess, "run", lambda *a, **k: out)
    assert listen._media_playing() is True


def test_media_playing_false_without_pactl(monkeypatch):
    monkeypatch.setattr(listen.shutil, "which", lambda name: None)
    assert listen._media_playing() is False


# --- echo-cancel: capture from a non-default source ---

def test_audio_command_targets_configured_source(monkeypatch):
    monkeypatch.setattr(listen.shutil, "which", lambda name: "/usr/bin/pw-cat")
    cfg = config.defaults()
    cfg["audio"]["source"] = "echocancel_source"
    cmd = listen._audio_command(cfg)
    assert "--target" in cmd and "echocancel_source" in cmd


def test_audio_command_no_target_for_default(monkeypatch):
    monkeypatch.setattr(listen.shutil, "which", lambda name: "/usr/bin/pw-cat")
    assert "--target" not in listen._audio_command(config.defaults())


# --- wake word (Alexa-style "voxpane …") ---

def test_wake_passthrough_when_unset():
    assert listen.strip_wake_word("just some text", "") == "just some text"


def test_wake_extracts_request():
    assert listen.strip_wake_word("voxpane list the files", "voxpane") == "list the files"


def test_wake_matches_alias():
    aliases = config.defaults()["listen"]["wake_aliases"]
    result = listen.strip_wake_word("vox pane open the readme", "voxpane", aliases)
    assert result == "open the readme"


def test_wake_ignores_unaddressed_speech():
    assert listen.strip_wake_word("what time is it", "voxpane") is None


def test_wake_word_alone_returns_empty_request():
    assert listen.strip_wake_word("Voxpane.", "voxpane") == ""


def test_wake_strips_leading_punctuation():
    assert listen.strip_wake_word("voxpane, run the tests", "voxpane") == "run the tests"
