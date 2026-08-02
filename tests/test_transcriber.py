"""Tests for the whisper-cli transcriber (M1). Subprocess mocked."""

from __future__ import annotations

import pytest

from voxpane import config, transcriber


def _cfg_with_model(tmp_path, **whisper):
    cfg = config.defaults()
    model = tmp_path / "model.bin"
    model.write_bytes(b"x")
    cfg["whisper"]["model"] = str(model)
    cfg["whisper"].update(whisper)
    return cfg, model


def test_builds_command_and_returns_stripped_text(tmp_path, monkeypatch):
    cfg, model = _cfg_with_model(tmp_path, initial_prompt="git commit", threads=4)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd

        class R:
            returncode = 0
            stdout = "  hello world  \n"
            stderr = ""

        return R()

    monkeypatch.setattr(transcriber.subprocess, "run", fake_run)
    monkeypatch.setattr(transcriber.shutil, "which", lambda name: f"/usr/bin/{name}")

    out = transcriber.transcribe_file(wav, cfg)

    assert out == "hello world"
    cmd = seen["cmd"]
    assert cmd[0] == "whisper-cli"
    assert "-m" in cmd and str(model) in cmd
    assert "-f" in cmd and str(wav) in cmd
    assert "-nt" in cmd and "-np" in cmd
    assert "-t" in cmd and "4" in cmd
    assert "--prompt" in cmd and "git commit" in cmd


def test_raises_on_nonzero_exit(tmp_path, monkeypatch):
    cfg, _ = _cfg_with_model(tmp_path)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
            stdout = ""
            stderr = "boom"

        return R()

    monkeypatch.setattr(transcriber.subprocess, "run", fake_run)
    monkeypatch.setattr(transcriber.shutil, "which", lambda name: f"/usr/bin/{name}")

    with pytest.raises(RuntimeError, match="boom"):
        transcriber.transcribe_file(wav, cfg)


def test_raises_when_binary_missing(tmp_path, monkeypatch):
    cfg, _ = _cfg_with_model(tmp_path)
    monkeypatch.setattr(transcriber.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="not found"):
        transcriber.transcribe_file(tmp_path / "a.wav", cfg)


def test_raises_when_model_missing(tmp_path, monkeypatch):
    cfg = config.defaults()
    cfg["whisper"]["model"] = str(tmp_path / "nope.bin")
    monkeypatch.setattr(transcriber.shutil, "which", lambda name: f"/usr/bin/{name}")
    with pytest.raises(RuntimeError, match="model missing"):
        transcriber.transcribe_file(tmp_path / "a.wav", cfg)
