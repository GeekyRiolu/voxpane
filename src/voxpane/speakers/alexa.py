"""Alexa backend — Alexa's real voice over WiFi — milestone M8.

Drives ``alexa-cli`` (``alexa say|announce --device <name>``). Preferred backend
when it works, but the endpoint is unofficial and WILL fail eventually (network,
auth expiry) — every failure raises :class:`SpeakerError` so the chain falls
through. ``say`` = no chime, ``announce`` = chime.
"""

from __future__ import annotations

import shutil
import subprocess

from .base import Speaker, SpeakerError


class AlexaSpeaker(Speaker):
    name = "alexa"

    def _conf(self) -> dict:
        return self.cfg["speak"]["alexa"]

    def available(self) -> bool:
        command = self._conf().get("command", "alexa")
        if not shutil.which(command):
            return False
        try:  # `alexa devices` returns 0 only when authed and online
            result = subprocess.run(
                [command, "devices"], capture_output=True, text=True, timeout=6
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def speak(self, text: str) -> None:
        conf = self._conf()
        command = conf.get("command", "alexa")
        if not shutil.which(command):
            raise SpeakerError("alexa CLI not found")
        args = [command, conf.get("mode", "say"), text]
        if conf.get("device"):
            args += ["--device", conf["device"]]
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SpeakerError(f"alexa: {exc}") from exc
        if result.returncode != 0:
            raise SpeakerError(f"alexa: {result.stderr.strip() or result.returncode}")
