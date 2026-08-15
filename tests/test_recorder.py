"""Tests for the recorder (M1). Every subprocess is mocked."""

from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace

import pytest

from voxpane import config, paths, recorder


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    # Isolate all runtime state (record.json, record.pid) under a temp dir.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


class FakePopen:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.pid = 4242
        FakePopen.last = self


def test_start_builds_pw_record_and_persists_state(runtime, monkeypatch):
    monkeypatch.setattr(recorder, "is_recording", lambda: False)
    monkeypatch.setattr(recorder.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(recorder.subprocess, "Popen", FakePopen)

    wav = recorder.start(config.defaults())

    assert str(wav).startswith("/tmp/vp-") and str(wav).endswith(".wav")
    cmd = FakePopen.last.cmd
    assert "pw-record" in cmd
    assert "--rate=16000" in cmd and "--channels=1" in cmd and "--format=s16" in cmd
    assert str(wav) in cmd

    state = json.loads(paths.record_state_file().read_text())
    assert state["pid"] == 4242 and state["wav"] == str(wav)


def test_start_falls_back_to_parecord_without_pw_record(runtime, monkeypatch):
    monkeypatch.setattr(recorder, "is_recording", lambda: False)
    monkeypatch.setattr(recorder.shutil, "which",
                        lambda name: None if name == "pw-record" else f"/usr/bin/{name}")
    monkeypatch.setattr(recorder.subprocess, "Popen", FakePopen)

    recorder.start(config.defaults())

    cmd = FakePopen.last.cmd
    assert "parecord" in cmd and "--format=s16le" in cmd
    assert json.loads(paths.record_state_file().read_text())["tool"] == "parecord"


def test_start_raises_when_no_recorder_installed(runtime, monkeypatch):
    monkeypatch.setattr(recorder, "is_recording", lambda: False)
    absent = {"pw-record", "parecord"}
    monkeypatch.setattr(recorder.shutil, "which",
                        lambda name: None if name in absent else f"/usr/bin/{name}")
    with pytest.raises(RuntimeError, match="no recorder"):
        recorder.start(config.defaults())


def test_start_is_noop_when_already_recording(runtime, monkeypatch):
    monkeypatch.setattr(recorder, "is_recording", lambda: True)
    paths.ensure(paths.runtime_dir())
    paths.record_state_file().write_text(
        json.dumps({"wav": "/tmp/vp-1.wav", "pid": 1, "started_at": 0})
    )

    def explode(*a, **k):
        raise AssertionError("must not spawn a second recorder")

    monkeypatch.setattr(recorder.subprocess, "Popen", explode)
    assert str(recorder.start(config.defaults())) == "/tmp/vp-1.wav"


def test_stop_sends_sigint_never_sigkill(runtime, monkeypatch):
    paths.ensure(paths.runtime_dir())
    wav = runtime / "vp.wav"
    wav.write_bytes(b"RIFF____WAVE")
    paths.record_state_file().write_text(
        json.dumps({"wav": str(wav), "pid": 999_999, "started_at": 0})
    )

    ran: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        ran.append(cmd)

        class R:  # pgrep -> "not found" so the drain loop exits immediately
            returncode = 1

        return R()

    def which(name):
        return f"/usr/bin/{name}" if name in ("pkill", "pgrep") else None

    monkeypatch.setattr(recorder.subprocess, "run", fake_run)
    monkeypatch.setattr(recorder.shutil, "which", which)

    result = recorder.stop(timeout_s=0.3)

    assert result == wav
    joined = [" ".join(c) for c in ran]
    assert "pkill -INT -x pw-record" in joined
    assert not any("-KILL" in j or "-9" in j for j in joined)
    assert not paths.record_state_file().exists()  # state cleared


def test_stop_signals_the_recorder_named_in_state(runtime, monkeypatch):
    paths.ensure(paths.runtime_dir())
    wav = runtime / "vp.wav"
    wav.write_bytes(b"RIFF____WAVE")
    paths.record_state_file().write_text(
        json.dumps({"wav": str(wav), "pid": 999_999, "tool": "parecord", "started_at": 0})
    )
    ran: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        ran.append(cmd)
        return type("R", (), {"returncode": 1})()

    monkeypatch.setattr(recorder.subprocess, "run", fake_run)
    monkeypatch.setattr(recorder.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in ("pkill", "pgrep") else None)

    recorder.stop(timeout_s=0.3)
    assert "pkill -INT -x parecord" in [" ".join(c) for c in ran]


def test_stop_returns_none_when_idle(runtime, monkeypatch):
    monkeypatch.setattr(recorder, "_running_recorder", lambda: None)
    assert recorder.stop(timeout_s=0.1) is None


# ------------------------------------------------------------------- windows

def test_win_pid_alive_uses_tasklist_not_os_kill(monkeypatch):
    seen = {}

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return SimpleNamespace(stdout=" 4242 Console")

    monkeypatch.setattr(recorder.subprocess, "run", fake_run)
    assert recorder._win_pid_alive(4242) is True
    assert seen["cmd"][0] == "tasklist"


def test_start_windows_spawns_winrec_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(recorder.osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # runtime dir isolation on Windows
    monkeypatch.setattr(recorder, "is_recording", lambda: False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())  # sounddevice present
    monkeypatch.setattr(recorder.subprocess, "Popen", FakePopen)

    wav = recorder.start(config.defaults())

    cmd = FakePopen.last.cmd
    assert "voxpane.winrec" in cmd and str(wav) in cmd
    state = json.loads(paths.record_state_file().read_text())
    assert state["tool"] == "winrec" and state["stop_file"].endswith("record.stop")


def test_start_windows_raises_without_sounddevice(monkeypatch, tmp_path):
    monkeypatch.setattr(recorder.osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(recorder, "is_recording", lambda: False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)  # not installed
    with pytest.raises(RuntimeError, match="sounddevice not installed"):
        recorder.start(config.defaults())


def test_stop_windows_signals_via_stop_file(monkeypatch, tmp_path):
    monkeypatch.setattr(recorder.osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths.ensure(paths.runtime_dir())
    wav = tmp_path / "vp.wav"
    wav.write_bytes(b"RIFF____WAVE")
    stop_file = paths.runtime_dir() / "record.stop"
    paths.record_state_file().write_text(json.dumps(
        {"wav": str(wav), "pid": 999_999, "tool": "winrec", "stop_file": str(stop_file)}))

    seen = {}

    def fake_alive(pid):  # the sentinel must be written by the time we poll liveness
        seen["stop_written"] = stop_file.exists()
        return False

    monkeypatch.setattr(recorder, "_pid_alive", fake_alive)
    result = recorder.stop(timeout_s=0.3)

    assert result == wav
    assert seen["stop_written"] is True
    assert not paths.record_state_file().exists()  # state cleared
