"""Windows push-to-talk capture worker.

``recorder.start`` spawns this detached on Windows (there is no ``pw-record`` there).
It records 16 kHz mono s16 WAV via ``sounddevice`` (WASAPI) until a stop-file appears
or ``max_seconds`` elapses, then finalises the WAV and exits. ``recorder.stop`` creates
the stop-file. Filesystem sentinels replace the POSIX SIGINT-finalises-the-WAV contract,
which does not port to Windows (``os.kill`` there terminates rather than signals).

Frames are written incrementally and the WAV is closed cleanly on exit, so the header
is always finalised. Run as: ``python -m voxpane.winrec <wav> <rate> <max_s> <stop_file>
[device]``.
"""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

_BLOCK_SECONDS = 0.1  # read the mic in 100 ms chunks


def record(wav_path: str, rate: int, max_seconds: int, stop_file: str,
           device: str | None = None) -> None:
    import sounddevice as sd

    stop = Path(stop_file)
    deadline = time.time() + max_seconds if max_seconds > 0 else None
    block = max(1, int(rate * _BLOCK_SECONDS))
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # s16 = 2 bytes/sample
        wf.setframerate(rate)
        with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16",
                               device=device) as stream:
            while not stop.exists() and (deadline is None or time.time() < deadline):
                data, _overflowed = stream.read(block)
                wf.writeframes(bytes(data))
    # Acknowledge the stop so `recorder.stop` knows we finalised and exited.
    stop.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    wav_path, rate, max_seconds, stop_file = argv[1], int(argv[2]), int(argv[3]), argv[4]
    device = argv[5] if len(argv) > 5 and argv[5] else None
    record(wav_path, rate, max_seconds, stop_file, device)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
