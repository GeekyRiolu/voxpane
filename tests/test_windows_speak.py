"""Windows spoken-output paths (WS1): msvcrt lock, toast, sounddevice playback, hush.

Exercised on Linux by forcing osutil.IS_WINDOWS and injecting fake msvcrt/sounddevice.
"""

from __future__ import annotations

import importlib.util
import sys
import types
import wave
from types import SimpleNamespace

from voxpane import config, hush, notify, paths, speakers
from voxpane.speakers import bluetooth


def test_speak_lock_uses_msvcrt_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(speakers.osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    calls = []
    fake = types.ModuleType("msvcrt")
    fake.LK_LOCK, fake.LK_UNLCK = 1, 0
    fake.locking = lambda fd, mode, n: calls.append(mode)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)

    with speakers._speak_lock():
        pass

    assert calls == [fake.LK_LOCK, fake.LK_UNLCK]  # acquired then released


def test_notify_windows_builds_balloon(monkeypatch):
    monkeypatch.setattr(notify.osutil, "IS_WINDOWS", True)
    monkeypatch.setattr(notify.shutil, "which",
                        lambda n: "pwsh" if n in ("pwsh", "powershell") else None)
    seen = {}
    monkeypatch.setattr(notify.subprocess, "Popen", lambda argv, **k: seen.update(argv=argv))

    rid = notify.notify("voxpane", "done — 3 files", replace_id=42)

    assert "ShowBalloonTip" in seen["argv"][-1]
    assert rid == 42  # replace_id flows back unchanged (balloons can't be replaced)


def test_notify_windows_no_powershell_is_silent(monkeypatch):
    monkeypatch.setattr(notify.osutil, "IS_WINDOWS", True)
    monkeypatch.setattr(notify.shutil, "which", lambda n: None)
    # Must not raise even with nothing to notify through.
    assert notify.notify("voxpane", "hi") is None


def test_bluetooth_available_windows_needs_sounddevice(monkeypatch):
    monkeypatch.setattr(bluetooth.osutil, "IS_WINDOWS", True)
    monkeypatch.setattr(bluetooth, "_piper_bin", lambda: "piper")
    spk = bluetooth.BluetoothSpeaker(config.defaults())

    monkeypatch.setattr(importlib.util, "find_spec", lambda n: object())
    assert spk.available() is True
    monkeypatch.setattr(importlib.util, "find_spec", lambda n: None)
    assert spk.available() is False


def test_bluetooth_play_windows_streams_wav_and_clears_pid(monkeypatch, tmp_path):
    monkeypatch.setattr(bluetooth.osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    wav = tmp_path / "s.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x01" * 5000)  # 5000 samples s16 = 10000 bytes

    writes = {"bytes": 0}

    class FakeOut:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, data):
            writes["bytes"] += len(data)

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.RawOutputStream = lambda **k: FakeOut()
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    bluetooth.BluetoothSpeaker(config.defaults())._play_windows(wav)

    assert writes["bytes"] == 10000  # whole file streamed to the output
    assert not paths.play_pid_file().exists()  # pid cleaned up


def test_hush_windows_uses_taskkill(monkeypatch, tmp_path):
    monkeypatch.setattr(hush.osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths.ensure(paths.runtime_dir())
    paths.play_pid_file().write_text("4242")

    seen = {}
    monkeypatch.setattr(hush.subprocess, "run",
                        lambda argv, **k: seen.update(argv=argv) or SimpleNamespace(returncode=0))

    assert hush.hush() is True
    assert seen["argv"][:2] == ["taskkill", "/F"] and "4242" in seen["argv"]
    assert not paths.play_pid_file().exists()  # marker cleared
