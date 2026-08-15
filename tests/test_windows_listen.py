"""Windows hands-free capture (WS4): the mic-source abstraction.

POSIX pipes pw-cat/parec into a subprocess; Windows reads a sounddevice stream. Both
must yield fixed-size (_BYTES_PER_FRAME) s16 frames so the VAD/endpointer are unaffected.
"""

from __future__ import annotations

import io
import sys
import types

from voxpane import config, listen


def test_open_mic_picks_backend_by_os(monkeypatch):
    monkeypatch.setattr(listen, "_SoundDeviceMic", lambda cfg: "SD")
    monkeypatch.setattr(listen, "_SubprocessMic", lambda cfg: "SUB")
    monkeypatch.setattr(listen.osutil, "IS_WINDOWS", True)
    assert listen._open_mic(config.defaults()) == "SD"
    monkeypatch.setattr(listen.osutil, "IS_WINDOWS", False)
    assert listen._open_mic(config.defaults()) == "SUB"


def test_subprocess_mic_reads_fixed_frames(monkeypatch):
    data = b"\x01\x02" * listen._BYTES_PER_FRAME  # exactly two full frames

    class FakeProc:
        stdout = io.BytesIO(data)

        def terminate(self):
            pass

    monkeypatch.setattr(listen.subprocess, "Popen", lambda *a, **k: FakeProc())
    mic = listen._SubprocessMic(config.defaults())
    frames = list(mic.frames())
    assert len(frames) == 2
    assert all(len(f) == listen._BYTES_PER_FRAME for f in frames)


def test_sounddevice_mic_yields_fixed_frames(monkeypatch):
    reads = {"n": 0}

    class FakeStream:
        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

        def read(self, n):
            reads["n"] += 1
            if reads["n"] <= 2:
                return (b"\x00\x01" * n, False)      # a full s16 frame (2*n bytes)
            return (b"\x00" * (2 * n - 2), False)    # short read -> ends the stream

    fake_sd = types.ModuleType("sounddevice")
    fake_sd.RawInputStream = lambda **k: FakeStream()
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    mic = listen._SoundDeviceMic(config.defaults())
    frames = list(mic.frames())
    assert len(frames) == 2
    assert all(len(f) == listen._BYTES_PER_FRAME for f in frames)
    mic.close()  # must not raise
