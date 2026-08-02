"""Tests for `voxpane doctor` (M0)."""

from __future__ import annotations

import copy

from voxpane import config, doctor


def _cfg():
    return copy.deepcopy(config.defaults())


def test_run_checks_returns_checks():
    checks = doctor.run_checks(_cfg())
    assert checks
    assert all(isinstance(c, doctor.Check) for c in checks)


def test_stt_fails_without_daemon_or_whisper(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))  # no daemon socket
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)  # no whisper-cli
    cfg = _cfg()
    cfg["whisper"]["model"] = str(tmp_path / "nope.bin")
    stt = next(c for c in doctor.run_checks(cfg) if c.name == "speech-to-text")
    assert not stt.ok and stt.hint


def test_stt_ok_when_daemon_socket_present(tmp_path, monkeypatch):
    import socket

    from voxpane import paths

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    paths.ensure(paths.runtime_dir())
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(paths.socket_path()))
    server.listen(1)
    try:
        stt = next(c for c in doctor.run_checks(_cfg()) if c.name == "speech-to-text")
        assert stt.ok and "daemon" in stt.detail
    finally:
        server.close()


def test_render_marks_pass_and_fail():
    ok = doctor.Check("thing", True, "found")
    bad = doctor.Check("other", False, "missing", "install it")
    rendered = doctor.render([ok, bad])
    assert "✓" in rendered and "✗" in rendered
    assert "install it" in rendered


def test_main_returns_int():
    out = []
    rc = doctor.main(_cfg(), printer=out.append)
    assert isinstance(rc, int)
    assert any("voxpane doctor" in line for line in out)
