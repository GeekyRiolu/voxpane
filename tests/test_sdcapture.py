"""Tests for the sounddevice capture worker (voxpane.sdcapture — macOS/Windows).

sounddevice isn't installed in this Linux test env, so we inject a fake module and
assert the worker records blocks, writes a valid WAV header, and acks the stop-file.
"""

from __future__ import annotations

import sys
import types
import wave

from voxpane import sdcapture


def _fake_sounddevice(stop_file, stop_after):
    """A sounddevice stand-in whose stream writes the stop-file after N reads."""
    state = {"reads": 0}

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, block):
            state["reads"] += 1
            if state["reads"] >= stop_after:
                stop_file.write_text("stop")  # end the capture loop next iteration
            return (b"\x00\x01" * block, False)

    mod = types.ModuleType("sounddevice")
    mod.RawInputStream = lambda **kwargs: FakeStream()
    return mod, state


def test_record_writes_valid_wav_and_acks_stop(tmp_path, monkeypatch):
    stop_file = tmp_path / "record.stop"
    wav = tmp_path / "out.wav"
    fake_sd, state = _fake_sounddevice(stop_file, stop_after=3)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    sdcapture.record(str(wav), 16000, 0, str(stop_file))

    with wave.open(str(wav)) as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getnframes() > 0  # captured at least one block
    assert state["reads"] == 3
    assert not stop_file.exists()  # worker acked by deleting the sentinel


def test_record_stops_at_max_seconds(tmp_path, monkeypatch):
    # No stop-file ever appears; the max_seconds deadline must end the loop.
    stop_file = tmp_path / "record.stop"
    wav = tmp_path / "out.wav"
    fake_sd, state = _fake_sounddevice(stop_file, stop_after=10**9)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    # deadline = first time() (0.0) + max_seconds(1) = 1.0; loop reads while time < 1.0.
    vals = [0.0, 0.5, 1.5]
    monkeypatch.setattr(sdcapture.time, "time", lambda: vals.pop(0) if vals else 9.0)

    sdcapture.record(str(wav), 16000, 1, str(stop_file))
    assert state["reads"] == 1  # one block before the deadline tripped
    with wave.open(str(wav)) as wf:
        assert wf.getnframes() > 0
    assert not stop_file.exists()
