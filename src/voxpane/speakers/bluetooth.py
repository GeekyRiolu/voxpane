"""Bluetooth backend — local TTS to the Dot as an A2DP speaker — milestone M8.

Pipeline: ``piper`` synthesises -> ``sox`` pads with ``lead_silence_ms`` of
lead-in silence -> ``pw-play --target <sink>``. Always works (not Alexa's voice).

The padding is not optional: A2DP links idle out, and the first ~500–800 ms after
a silent gap gets swallowed ("Done — three files" -> "ee files"). Autodetect the
``bluez_output.*`` sink when ``speak.bluetooth.sink`` is empty.
"""

from __future__ import annotations

from .base import Speaker


class BluetoothSpeaker(Speaker):
    name = "bluetooth"

    def available(self) -> bool:
        raise NotImplementedError("BluetoothSpeaker.available — milestone M8")

    def speak(self, text: str) -> None:
        raise NotImplementedError("BluetoothSpeaker.speak — milestone M8")
