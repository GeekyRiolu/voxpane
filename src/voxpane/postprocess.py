"""Rewrite a raw transcript into agent-ready text — milestone M4.

Pure and fully unit-tested (this is where the bugs live). Applies, in order:
  1. trailing-submit phrase — strip "send it" off the end and flag THIS utterance
     for auto-submit (never mutates global config);
  2. filler stripping (optional);
  3. slash commands ([text] values starting with "/") — START of utterance only;
  4. other [text] replacements (symbols, newline, @) — anywhere;
  5. [keys] actions — anywhere (emitted as key-name tokens; delivery-side key
     injection is a future refinement, so for now they land as literal text);
  6. [transforms] — identifier casing over the words that follow;
  7. [fixups] — common Whisper mishearings.

All matching is case-insensitive and word-boundary anchored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Conservative: only unambiguous fillers, so we never eat a meaningful word.
_FILLERS = ["um", "uh", "er", "ah", "erm", "hmm", "you know", "i mean"]


@dataclass(frozen=True)
class Rewritten:
    text: str
    submit: bool  # this utterance requested auto-submit (trailing phrase)


def _sub_phrase(text: str, phrase: str, value: str) -> str:
    pattern = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
    return pattern.sub(lambda _m: value, text)


def _strip_trailing_submit(text: str, phrase: str) -> tuple[str, bool]:
    match = re.search(r"\b" + re.escape(phrase) + r"\b[\s.!?]*$", text, re.IGNORECASE)
    if match:
        return text[: match.start()].rstrip(), True
    return text, False


def _strip_fillers(text: str) -> str:
    for filler in _FILLERS:
        text = re.sub(r"\b" + re.escape(filler) + r"\b", " ", text, flags=re.IGNORECASE)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _style(words: list[str], style: str) -> str:
    if not words:
        return ""
    if style == "camel":
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])
    if style == "pascal":
        return "".join(w.capitalize() for w in words)
    if style == "snake":
        return "_".join(w.lower() for w in words)
    if style == "kebab":
        return "-".join(w.lower() for w in words)
    return " ".join(words)


def _apply_transform(text: str, transforms: dict[str, str]) -> str:
    for phrase, style in transforms.items():
        match = re.search(r"\b" + re.escape(phrase) + r"\b\s+(.+)$", text, re.IGNORECASE)
        if match:
            return (text[: match.start()] + _style(match.group(1).split(), style)).strip()
    return text


def apply(transcript: str, commands: dict[str, Any], cfg: dict[str, Any]) -> Rewritten:
    """Rewrite ``transcript`` using the command dictionary and behaviour config."""
    behavior = cfg.get("behavior", {})
    text = " ".join(transcript.split())

    submit = False
    phrase = behavior.get("trailing_submit_phrase", "")
    if phrase:
        text, submit = _strip_trailing_submit(text, phrase)

    if behavior.get("strip_filler", False):
        text = _strip_fillers(text)

    text_map = commands.get("text", {})
    slash = {k: v for k, v in text_map.items() if isinstance(v, str) and v.startswith("/")}
    for key, value in slash.items():
        # Slash commands only fire at the start, so "the slash clear command"
        # stays literal.
        text = re.sub(r"^\s*" + re.escape(key) + r"\b", lambda _m, v=value: v, text, count=1,
                      flags=re.IGNORECASE)

    for key, value in text_map.items():
        if key not in slash:
            text = _sub_phrase(text, key, value)

    for key, value in commands.get("keys", {}).items():
        text = _sub_phrase(text, key, value)

    text = _apply_transform(text, commands.get("transforms", {}))

    for key, value in commands.get("fixups", {}).items():
        text = _sub_phrase(text, key, value)

    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return Rewritten(text=text, submit=submit)
