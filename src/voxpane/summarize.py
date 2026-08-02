"""Turn ledger facts + the last assistant message into one spoken sentence — M7.

Pure and fully unit-tested. Three modes:

  facts   template from the ledger alone, no network:
          "Four files changed in voxpane. Tests ran clean."
  llm     pipe ``last_assistant_message`` to ``claude -p --model haiku`` with a
          system prompt demanding one spoken sentence, < 30 words, no markdown,
          no paths read character by character, no code.
  hybrid  facts sentence + LLM clause; the LLM call is bounded by
          ``summary.llm_timeout_seconds`` and falls back to facts-only on
          timeout or error. (default)

Speech post-processing (ALL modes): collapse paths to basenames, expand or drop
file extensions, strip backticks, spell out symbols, then cap at ``max_chars``
on a sentence boundary. ``last_assistant_message`` is markdown and must never be
read verbatim ("backtick backtick backtick python").
"""

from __future__ import annotations

from typing import Any


def summarize(facts: dict[str, Any], last_message: str, cfg: dict[str, Any]) -> str:
    """Produce the final spoken string per ``summary.mode``, already speech-safe
    and capped at ``speak.max_chars``."""
    raise NotImplementedError("summarize.summarize — milestone M7")


def speechify(text: str, max_chars: int) -> str:
    """Apply the speech post-processing rules and cap on a sentence boundary."""
    raise NotImplementedError("summarize.speechify — milestone M7")
