"""The speaker interface — milestone M8."""

from __future__ import annotations

import abc
from typing import Any


class SpeakerError(RuntimeError):
    """A backend could not speak. The chain falls through to the next backend."""


class Speaker(abc.ABC):
    """One way to make the Dot (or the desktop) say a sentence."""

    name: str

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    @abc.abstractmethod
    def available(self) -> bool:
        """Cheap pre-flight: is this backend usable right now? (auth, sink, …)"""

    @abc.abstractmethod
    def speak(self, text: str) -> None:
        """Speak ``text`` or raise :class:`SpeakerError`."""
