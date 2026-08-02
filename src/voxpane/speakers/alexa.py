"""Alexa backend — Alexa's real voice over WiFi — milestone M8.

Drives ``alexa-cli`` (``alexa say|announce --device <name>``). Preferred backend
when it works, but the endpoint is unofficial and WILL fail eventually (network,
auth expiry) — every failure raises :class:`SpeakerError` so the chain falls
through. ``say`` = no chime, ``announce`` = chime.
"""

from __future__ import annotations

from .base import Speaker


class AlexaSpeaker(Speaker):
    name = "alexa"

    def available(self) -> bool:
        raise NotImplementedError("AlexaSpeaker.available — milestone M8")

    def speak(self, text: str) -> None:
        raise NotImplementedError("AlexaSpeaker.speak — milestone M8")
