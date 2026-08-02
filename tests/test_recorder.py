"""Tests for the recorder (M1). Every subprocess is mocked."""

from __future__ import annotations

import json

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
    assert "pkill -INT -f pw-record" in joined
    assert not any("-KILL" in j or "-9" in j for j in joined)
    assert not paths.record_state_file().exists()  # state cleared


def test_stop_returns_none_when_idle(runtime, monkeypatch):
    monkeypatch.setattr(recorder, "_pgrep_pw_record", lambda: False)
    assert recorder.stop(timeout_s=0.1) is None
