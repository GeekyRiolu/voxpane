"""Rewrite a raw transcript into agent-ready text — milestone M4.

Pure and fully unit-tested (this is where the bugs live). Applies, in order:
  1. exact-phrase replacements from ``commands.toml`` ``[text]``;
  2. key actions from ``[keys]`` (emitted as tmux key names, not literal text);
  3. identifier transforms from ``[transforms]`` (camel/snake/kebab/pascal case);
  4. common Whisper fixups from ``[fixups]``;
  5. optional filler stripping.

Rules that matter:
  * Case-insensitive, word-boundary anchored.
  * Slash commands (``/clear`` …) match at the START of the utterance only, so
    "the slash clear command" stays literal.
  * The trailing-submit phrase (default "send it") is stripped and, when present,
    marks THIS utterance for auto-submit — returned as a flag, never mutating
    global config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Rewritten:
    text: str
    submit: bool  # this utterance requested auto-submit (trailing phrase)


def apply(transcript: str, commands: dict[str, Any], cfg: dict[str, Any]) -> Rewritten:
    """Rewrite ``transcript`` using the command dictionary and behaviour config."""
    raise NotImplementedError("postprocess.apply — milestone M4")
