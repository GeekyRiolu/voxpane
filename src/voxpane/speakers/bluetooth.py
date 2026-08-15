"""Bluetooth backend — local TTS to the Dot as an A2DP speaker — milestone M8.

Pipeline: ``piper`` synthesises -> ``sox`` pads with ``lead_silence_ms`` of
lead-in silence -> ``pw-play --target <sink>``. Always works (not Alexa's voice).
On Windows there is no ``pw-play``/bluez, so playback streams to a WASAPI output via
``sounddevice`` (``_play_windows``) — set ``speak.bluetooth.sink`` to a device name,
or leave it empty for the default output.

The padding is not optional: A2DP links idle out, and the first ~500–800 ms after
a silent gap gets swallowed ("Done — three files" -> "ee files"). Autodetect the
``bluez_output.*`` sink when ``speak.bluetooth.sink`` is empty.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from .. import osutil, paths
from .base import Speaker, SpeakerError


def _piper_bin() -> str | None:
    return shutil.which("piper") or shutil.which("piper-tts")


class BluetoothSpeaker(Speaker):
    name = "bluetooth"

    def _conf(self) -> dict:
        return self.cfg["speak"]["bluetooth"]

    def _sink(self) -> str | None:
        configured = self._conf().get("sink", "")
        if configured:
            return configured
        if not shutil.which("pactl"):
            return None
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=5
            )
        except (OSError, subprocess.SubprocessError):
            return None
        for line in result.stdout.splitlines():
            for token in line.split():
                if token.startswith("bluez_output."):
                    return token
        return None

    def available(self) -> bool:
        if _piper_bin() is None:
            return False
        if osutil.IS_WINDOWS:  # plays to a WASAPI device — no bluez sink needed
            import importlib.util
            return importlib.util.find_spec("sounddevice") is not None
        return self._sink() is not None

    def speak(self, text: str) -> None:
        piper = _piper_bin()
        if not piper:
            raise SpeakerError("piper not found")
        model = Path(self._conf().get("piper_model", "")).expanduser()
        if not model.is_file():
            raise SpeakerError(f"piper model missing: {model}")

        if osutil.IS_WINDOWS:
            with tempfile.TemporaryDirectory() as td:
                speech = Path(td) / "speech.wav"
                self._synthesize(piper, model, text, speech)
                self._play_windows(self._pad(speech, Path(td)))
            return

        sink = self._sink()
        if not sink:
            raise SpeakerError("no bluez sink")
        if not shutil.which("pw-play"):
            raise SpeakerError("pw-play not found")

        with tempfile.TemporaryDirectory() as td:
            speech = Path(td) / "speech.wav"
            self._synthesize(piper, model, text, speech)
            play_file = self._pad(speech, Path(td))
            self._play(sink, play_file)

    def _synthesize(self, piper: str, model: Path, text: str, out: Path) -> None:
        try:
            result = subprocess.run(
                [piper, "-m", str(model), "-f", str(out)],
                input=text, text=True, capture_output=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SpeakerError(f"piper: {exc}") from exc
        if result.returncode != 0 or not out.exists():
            raise SpeakerError(f"piper failed: {result.stderr.strip() or result.returncode}")

    def _pad(self, speech: Path, workdir: Path) -> Path:
        lead_ms = int(self._conf().get("lead_silence_ms", 800))
        if not shutil.which("sox") or lead_ms <= 0:
            return speech
        pad = workdir / "pad.wav"
        padded = workdir / "out.wav"
        secs = str(lead_ms / 1000)
        try:
            subprocess.run(
                ["sox", "-n", "-r", "22050", "-c", "1", str(pad), "trim", "0.0", secs],
                check=True, capture_output=True, timeout=10,
            )
            subprocess.run(
                ["sox", str(pad), str(speech), str(padded)],
                check=True, capture_output=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return speech  # padding is best-effort
        return padded

    def _play(self, sink: str, wav: Path) -> None:
        # Popen (not run) so `voxpane hush` can SIGTERM this pid mid-playback.
        try:
            proc = subprocess.Popen(
                ["pw-play", "--target", sink, str(wav)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise SpeakerError(f"pw-play: {exc}") from exc
        paths.ensure(paths.runtime_dir())
        paths.play_pid_file().write_text(str(proc.pid))
        try:
            _, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise SpeakerError("pw-play timed out") from None
        finally:
            try:
                paths.play_pid_file().unlink()
            except FileNotFoundError:
                pass
        # 0 = ok; -SIGTERM = a deliberate `voxpane hush`, not an error.
        if proc.returncode not in (0, -signal.SIGTERM):
            detail = (err or b"").decode(errors="replace").strip() or proc.returncode
            raise SpeakerError(f"pw-play: {detail}")

    def _play_windows(self, wav: Path) -> None:
        """Stream the WAV to a WASAPI output via sounddevice (no numpy). Uses
        ``speak.bluetooth.sink`` as the device if set, else the default output. Records
        our own pid so ``voxpane hush`` can taskkill this process mid-utterance."""
        import wave

        import sounddevice as sd

        device = self._conf().get("sink") or None
        paths.ensure(paths.runtime_dir())
        paths.play_pid_file().write_text(str(os.getpid()))
        try:
            with wave.open(str(wav), "rb") as wf:
                sr, ch, sw = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
                dtype = {1: "int8", 2: "int16", 4: "int32"}.get(sw, "int16")
                with sd.RawOutputStream(samplerate=sr, channels=ch, dtype=dtype,
                                        device=device) as stream:
                    while True:
                        data = wf.readframes(4096)
                        if not data:
                            break
                        stream.write(data)
        except Exception as exc:
            raise SpeakerError(f"sounddevice playback: {exc}") from exc
        finally:
            try:
                paths.play_pid_file().unlink()
            except FileNotFoundError:
                pass
