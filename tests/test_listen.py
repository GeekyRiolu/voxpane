"""Tests for the hands-free listen mode's pure logic (VAD endpointer)."""

from __future__ import annotations

import array
from types import SimpleNamespace

from voxpane import config, listen, paths

# Loud dummy PCM (constant amplitude 6000) so utterances clear the min_rms gate;
# transcription is stubbed in these tests, so only the loudness matters.
_LOUD = array.array("h", [6000] * 640).tobytes()


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
    monkeypatch.setattr(config, "load", config.defaults)  # release() reads always_on
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


def test_is_terminal_window_true_for_terminals():
    assert listen._is_terminal_window({"class": "Alacritty", "title": "nvim"})
    assert listen._is_terminal_window({"class": "com.mitchellh.ghostty", "title": ""})


def test_is_terminal_window_true_for_claude_by_title():
    assert listen._is_terminal_window({"class": "weird-wm", "title": "claude — ~/work"})


def test_is_terminal_window_false_for_browser():
    assert not listen._is_terminal_window({"class": "chromium", "title": "YouTube"})
    assert not listen._is_terminal_window(None)


def test_capture_window_skips_non_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(
        listen, "_active_window",
        lambda: {"address": "0x1", "class": "chromium", "title": "a video"},
    )
    listen._capture_window("s1")
    assert listen._load_windows() == {}  # a browser must not become "the Claude window"


def test_capture_window_remembers_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(
        listen, "_active_window",
        lambda: {"address": "0x2", "class": "Alacritty", "title": "claude"},
    )
    listen._capture_window("s1")
    assert listen._load_windows()["s1"]["address"] == "0x2"


def test_resolve_folder_matches_repo_by_voice(tmp_path):
    for name in ("voxpane", "SETU_v2", "agent_bot"):
        (tmp_path / name).mkdir()
    base = str(tmp_path)
    assert listen._resolve_folder("voxpane", base) == str(tmp_path / "voxpane")   # exact
    assert listen._resolve_folder("setu", base) == str(tmp_path / "SETU_v2")       # substring
    assert listen._resolve_folder("open the voxpane repo", base) == str(tmp_path / "voxpane")
    assert listen._resolve_folder("", base) == base                               # bare -> base
    assert listen._resolve_folder("nothing like this", base) == base              # no match -> base


def test_stop_removes_its_own_pidfile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    paths.ensure(paths.runtime_dir())
    pidfile = paths.listener_pid_file()
    pidfile.write_text("111")
    monkeypatch.setattr(listen, "_alive", lambda pid: False)  # already gone
    monkeypatch.setattr(listen, "_all_listener_pids", list)    # no strays
    listen.stop()
    assert not pidfile.exists()


def test_stop_keeps_pidfile_reclaimed_by_a_new_listener(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    paths.ensure(paths.runtime_dir())
    pidfile = paths.listener_pid_file()
    pidfile.write_text("111")
    monkeypatch.setattr(listen, "_alive", lambda pid: False)
    monkeypatch.setattr(listen, "_all_listener_pids", list)  # no strays
    # stop() targets 111, but a fresh listener reclaims the file before the guard.
    reads = iter([111, 222])
    monkeypatch.setattr(listen, "_read_pid", lambda p: next(reads))
    listen.stop()
    assert pidfile.exists()  # 222 != 111 -> must not remove the new listener's pid file


def test_stop_sweeps_orphan_listeners(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    paths.ensure(paths.runtime_dir())
    paths.listener_pid_file().write_text("111")            # tracked listener
    monkeypatch.setattr(listen, "_all_listener_pids", lambda: [999])  # an orphan too
    monkeypatch.setattr(listen, "_alive", lambda pid: True)
    killed = []
    monkeypatch.setattr(listen.os, "kill", lambda pid, sig: killed.append(pid))
    listen.stop()
    assert set(killed) == {111, 999}  # both the tracked one AND the orphan get killed


# --- always_on: session end must not stop a standalone listener ---

def test_release_stops_last_when_not_always_on(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    stops = []
    monkeypatch.setattr(listen, "stop", lambda: stops.append(1))
    monkeypatch.setattr(config, "load", config.defaults)  # always_on defaults False
    listen._write_sessions({"only"})
    listen.release("only")
    assert stops == [1]


def test_release_keeps_listener_when_always_on(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    stops = []
    monkeypatch.setattr(listen, "stop", lambda: stops.append(1))

    def always_on_cfg():
        cfg = config.defaults()
        cfg["listen"]["always_on"] = True
        return cfg

    monkeypatch.setattr(config, "load", always_on_cfg)
    listen._write_sessions({"only"})
    listen.release("only")
    assert stops == []  # standalone listener survives the last session ending


# --- hybrid mode: focus decides dictation vs wake-gating ---

_HYBRID_CFG = {
    "listen": {
        "wake_word": "voxpane", "wake_aliases": ["vox pane"], "pause_on_playback": True,
        "pause_media_on_wake": True, "auto_submit": True, "stop_words": ["stop"],
        "focus_match": "",
    },
    "delivery": {"mode": "focus"},
}


def _prep_utterance(monkeypatch, tmp_path, *, transcript, window, media=False, captured=None):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    paths.ensure(paths.runtime_dir())  # handle_utterance writes a temp wav here
    monkeypatch.setattr("voxpane.transcriber.transcribe", lambda wav, cfg: transcript)
    monkeypatch.setattr(listen, "_active_window", lambda: window)
    monkeypatch.setattr(listen, "_media_playing", lambda: media)
    monkeypatch.setattr(listen, "_load_windows", lambda: captured or {})
    monkeypatch.setattr("voxpane.config.load_commands", lambda: {})
    monkeypatch.setattr(
        "voxpane.postprocess.apply",
        lambda text, cmds, cfg: SimpleNamespace(text=text, submit=False),
    )


_TERM = {"class": "Alacritty", "title": "claude", "address": "0x1"}
_BROWSER = {"class": "chromium", "title": "YouTube", "address": "0x9"}


def test_dictates_when_terminal_focused(tmp_path, monkeypatch):
    _prep_utterance(monkeypatch, tmp_path, transcript="list the files", window=_TERM)
    got = {}
    monkeypatch.setattr("voxpane.deliver.deliver",
                        lambda text, cfg, submit=True: got.update(text=text, submit=submit))
    assert listen.handle_utterance(_LOUD, _HYBRID_CFG) == "list the files"
    assert got["text"] == "list the files"  # no wake word needed when focused


def test_wake_opens_session_even_when_terminal_focused(tmp_path, monkeypatch):
    # Wake word wins over dictation: "voxpane <repo>" opens a session, doesn't type.
    _prep_utterance(monkeypatch, tmp_path, transcript="voxpane voxpane", window=_TERM)
    monkeypatch.setattr(listen, "_pause_media", lambda: None)
    opened, delivered = [], []
    monkeypatch.setattr(listen, "_wake_open_session", lambda req, cfg: opened.append(req))
    monkeypatch.setattr("voxpane.deliver.deliver",
                        lambda text, cfg, submit=True: delivered.append(text))
    listen.handle_utterance(_LOUD, _HYBRID_CFG)
    assert opened == ["voxpane"] and delivered == []


def test_no_dictation_over_media_when_focused(tmp_path, monkeypatch):
    _prep_utterance(monkeypatch, tmp_path, transcript="hello there", window=_TERM, media=True)
    got = {}
    monkeypatch.setattr("voxpane.deliver.deliver",
                        lambda text, cfg, submit=True: got.update(text=text))
    assert listen.handle_utterance(_LOUD, _HYBRID_CFG) is None
    assert got == {}


def test_unaddressed_speech_ignored_when_browser_focused(tmp_path, monkeypatch):
    _prep_utterance(monkeypatch, tmp_path, transcript="what time is it", window=_BROWSER)
    monkeypatch.setattr(listen, "_pause_media", lambda: None)
    calls = []
    monkeypatch.setattr(listen, "_wake_open_session", lambda req, cfg: calls.append(req))
    assert listen.handle_utterance(_LOUD, _HYBRID_CFG) is None
    assert calls == []  # no wake word + not focused -> ignored


def test_wake_opens_session_when_browser_focused(tmp_path, monkeypatch):
    _prep_utterance(monkeypatch, tmp_path, transcript="voxpane setu", window=_BROWSER)
    monkeypatch.setattr(listen, "_pause_media", lambda: None)
    calls = []
    monkeypatch.setattr(listen, "_wake_open_session", lambda req, cfg: calls.append(req))
    listen.handle_utterance(_LOUD, _HYBRID_CFG)
    assert calls == ["setu"]


def test_dictates_into_any_focused_terminal(tmp_path, monkeypatch):
    # No fragile captured-window matching: focused on ANY terminal -> dictate, even
    # if a different window was captured. (Robustness over precision.)
    _prep_utterance(
        monkeypatch, tmp_path, transcript="run the tests",
        window={"class": "Alacritty", "title": "htop", "address": "0xOTHER"},
        captured={"s": {"address": "0xCLAUDE"}},
    )
    got = {}
    monkeypatch.setattr("voxpane.deliver.deliver",
                        lambda text, cfg, submit=True: got.update(text=text))
    assert listen.handle_utterance(_LOUD, _HYBRID_CFG) == "run the tests"
    assert got["text"] == "run the tests"


# --- Whisper hallucination filter ---

def test_is_ignorable_matches_whisper_hallucinations():
    cfg = {"listen": {}}  # built-in fragment filter, no user phrases
    assert listen._is_ignorable("Thanks for watching!", cfg)
    assert listen._is_ignorable("thank you.", cfg)
    assert listen._is_ignorable("You", cfg)
    assert listen._is_ignorable("", cfg)
    # compound outros that don't match any single phrase but tile into fragments:
    assert listen._is_ignorable("Thanks for watching, I'll see you in the next video.", cfg)
    assert listen._is_ignorable("Thank you so much for watching everyone!", cfg)
    # real speech (has a content word) is never dropped:
    assert not listen._is_ignorable("run the tests", cfg)
    assert not listen._is_ignorable("thank you, now run the tests", cfg)
    assert not listen._is_ignorable("see you after you commit the code", cfg)


def test_ignore_phrases_are_additive(monkeypatch):
    cfg = {"listen": {"ignore_phrases": ["computer engage"]}}
    assert listen._is_ignorable("Computer, engage!", cfg)   # user phrase
    assert listen._is_ignorable("thanks for watching", cfg)  # built-ins still apply
    assert not listen._is_ignorable("open the file", cfg)


# --- source-side loudness gate (don't feed Whisper near-silence) ---

def test_utterance_rms_distinguishes_silence_from_speech():
    silence = b"\x00\x00" * 1600
    loud = array.array("h", [6000] * 1600).tobytes()
    assert listen._utterance_rms(silence) < 5
    assert 5900 < listen._utterance_rms(loud) < 6100
    assert listen._utterance_rms(b"") == 0.0


def test_handle_utterance_skips_near_silence(tmp_path, monkeypatch):
    _prep_utterance(monkeypatch, tmp_path, transcript="Thank you for watching", window=_TERM)
    reached = []
    monkeypatch.setattr("voxpane.transcriber.transcribe",
                        lambda wav, cfg: reached.append(1) or "x")
    delivered = []
    monkeypatch.setattr("voxpane.deliver.deliver",
                        lambda text, cfg, submit=True: delivered.append(text))
    silence = b"\x00\x00" * 1600
    assert listen.handle_utterance(silence, _HYBRID_CFG) is None
    assert reached == []      # Whisper never even asked about the silence
    assert delivered == []


# --- toggle: fully start/stop the listener with a key ---

def test_toggle_running_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    state = {"on": False}
    monkeypatch.setattr(listen, "is_listening", lambda: state["on"])
    monkeypatch.setattr(listen, "_all_listener_pids", list)  # no orphan strays
    monkeypatch.setattr(listen, "_spawn_listener", lambda: state.__setitem__("on", True))
    monkeypatch.setattr(listen, "stop", lambda: state.__setitem__("on", False))
    monkeypatch.setattr(listen, "_active_window", lambda: None)  # nothing to capture
    assert listen.toggle_running() is True    # was off -> spawn -> running
    assert state["on"] is True
    assert listen.toggle_running() is False   # was on -> stop -> off
    assert state["on"] is False


def test_hallucination_not_delivered_when_focused(tmp_path, monkeypatch):
    _prep_utterance(monkeypatch, tmp_path, transcript="Thanks for watching!", window=_TERM)
    delivered = []
    monkeypatch.setattr("voxpane.deliver.deliver",
                        lambda text, cfg, submit=True: delivered.append(text))
    assert listen.handle_utterance(_LOUD, _HYBRID_CFG) is None
    assert delivered == []  # the video's outro never reaches Claude
