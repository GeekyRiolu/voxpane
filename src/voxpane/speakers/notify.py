"""Notify backend — the floor of the fallback chain — milestone M8.

When every audible backend fails, the summary still surfaces as a desktop
notification. This backend is always ``available()`` and must never raise: it is
what guarantees "no path raises". Delegates to :mod:`voxpane.notify`.
"""

from __future__ import annotations

from .. import notify as desktop_notify
from .base import Speaker


class NotifySpeaker(Speaker):
    name = "notify"

    def available(self) -> bool:
        return True

    def speak(self, text: str) -> None:
        desktop_notify.notify("voxpane", text, icon="audio-speakers")
