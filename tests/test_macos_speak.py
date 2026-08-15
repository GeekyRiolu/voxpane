"""macOS spoken output (M2): afplay playback + osascript notification.

Exercised on Linux by forcing osutil.IS_MACOS and mocking subprocess.
"""

from __future__ import annotations

from voxpane import config, notify, paths
from voxpane.speakers import bluetooth


def test_bluetooth_available_macos_needs_afplay(monkeypatch):
    monkeypatch.setattr(bluetooth.osutil, "IS_WINDOWS", False)
    monkeypatch.setattr(bluetooth.osutil, "IS_MACOS", True)
    monkeypatch.setattr(bluetooth, "_piper_bin", lambda: "piper")
    spk = bluetooth.BluetoothSpeaker(config.defaults())

    monkeypatch.setattr(bluetooth.shutil, "which",
                        lambda n: "/usr/bin/afplay" if n == "afplay" else None)
    assert spk.available() is True
    monkeypatch.setattr(bluetooth.shutil, "which", lambda n: None)
    assert spk.available() is False


def test_bluetooth_play_macos_uses_afplay_and_clears_pid(monkeypatch, tmp_path):
    monkeypatch.setattr(bluetooth.osutil, "IS_MACOS", True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    seen = {}

    class FakeProc:
        pid = 4321
        returncode = 0

        def communicate(self, timeout=None):
            return (b"", b"")

    monkeypatch.setattr(bluetooth.subprocess, "Popen",
                        lambda argv, **k: seen.update(argv=argv) or FakeProc())

    wav = tmp_path / "s.wav"
    wav.write_bytes(b"RIFF____WAVE")
    bluetooth.BluetoothSpeaker(config.defaults())._play_macos(wav)

    assert seen["argv"][0] == "afplay" and str(wav) in seen["argv"]
    assert not paths.play_pid_file().exists()  # pid cleaned up


def test_notify_macos_uses_osascript(monkeypatch):
    monkeypatch.setattr(notify.osutil, "IS_WINDOWS", False)
    monkeypatch.setattr(notify.osutil, "IS_MACOS", True)
    monkeypatch.setattr(notify.shutil, "which", lambda n: "/usr/bin/osascript")
    seen = {}
    monkeypatch.setattr(notify.subprocess, "run", lambda argv, **k: seen.update(argv=argv))

    rid = notify.notify("voxpane", "done — 3 files", replace_id=7)

    assert seen["argv"][0] == "osascript" and "display notification" in seen["argv"][-1]
    assert rid == 7
