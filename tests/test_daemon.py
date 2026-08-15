"""Tests for the STT daemon protocol and client fallback (M5)."""

from __future__ import annotations

import socket
import threading

from voxpane import config, daemon, osutil, paths, transcriber


def test_handle_request_success():
    resp = daemon._handle_request({"wav": "a.wav"}, lambda w, lang, prompt: "  hi  ")
    assert resp == {"text": "hi"}


def test_handle_request_reports_errors():
    def boom(wav, lang, prompt):
        raise ValueError("nope")

    resp = daemon._handle_request({"wav": "x"}, boom)
    assert "error" in resp and "nope" in resp["error"]


def test_client_falls_back_when_no_socket(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))  # no daemon.sock present
    called = {}

    def fake_file(wav, cfg):
        called["hit"] = True
        return "subprocess text"

    monkeypatch.setattr(transcriber, "transcribe_file", fake_file)
    out = transcriber.transcribe(paths.record_state_file(), config.defaults())
    assert out == "subprocess text"
    assert called["hit"]


def test_daemon_socket_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    paths.ensure(paths.runtime_dir())

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(paths.socket_path()))
    server.listen(1)

    def fake_fn(wav, language, initial_prompt):
        return f"transcribed:{wav}:{language}"

    threading.Thread(target=daemon._serve, args=(server, fake_fn), daemon=True).start()

    cfg = config.defaults()
    out = transcriber.transcribe_via_daemon(paths.record_pid_file(), cfg)
    server.close()

    assert out == f"transcribed:{paths.record_pid_file()}:en"


def test_bind_server_windows_binds_loopback_tcp(tmp_path, monkeypatch):
    monkeypatch.setattr(osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    server = daemon._bind_server()
    try:
        host, port = server.getsockname()
        assert host == "127.0.0.1" and port > 0
        assert int(paths.daemon_port_file().read_text()) == port
    finally:
        server.close()
        daemon._cleanup_endpoint()
    assert not paths.daemon_port_file().exists()  # cleaned up


def test_daemon_tcp_roundtrip_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(osutil, "IS_WINDOWS", True)  # shared module → daemon + transcriber
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    server = daemon._bind_server()  # loopback TCP + port file (no AF_UNIX on Windows)

    def fake_fn(wav, language, initial_prompt):
        return f"tcp:{wav}:{language}"

    threading.Thread(target=daemon._serve, args=(server, fake_fn), daemon=True).start()
    out = transcriber.transcribe_via_daemon(paths.record_pid_file(), config.defaults())
    server.close()
    daemon._cleanup_endpoint()

    assert out == f"tcp:{paths.record_pid_file()}:en"


def test_daemon_connect_windows_none_without_port_file(tmp_path, monkeypatch):
    monkeypatch.setattr(osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert transcriber._daemon_connect() is None  # no daemon.port → fall back
