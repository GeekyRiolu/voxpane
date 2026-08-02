"""Turn ledger facts + the last assistant message into one spoken sentence — M7.

Three modes:
  facts   template from the ledger alone, no network.
  llm     pipe ``last_assistant_message`` to ``claude -p --model haiku`` asking
          for one spoken sentence, < 30 words, no markdown/paths/code.
  hybrid  facts sentence + LLM clause; the LLM call is bounded by
          ``summary.llm_timeout_seconds`` and falls back to facts-only on timeout
          or error. (default)

Speech post-processing (:func:`speechify`) runs on every LLM-derived string:
strip code fences and backticks, drop markdown, collapse file paths to their
basename, spell a couple of symbols, then cap at ``speak.max_chars`` on a
sentence boundary. ``last_assistant_message`` is markdown and must never be read
verbatim ("backtick backtick backtick python").
"""

from __future__ import annotations

import re
import shlex
import subprocess
from typing import Any


def facts_sentence(facts: dict[str, Any], project: str | None = None) -> str:
    """A deterministic factual summary from ledger facts (the network-free floor)."""
    where = f" in {project}" if project else ""
    n_files = facts.get("n_files", 0)
    if n_files:
        head = f"{n_files} file{'s' if n_files != 1 else ''} changed{where}."
    else:
        n_cmd = facts.get("n_commands", 0)
        if n_cmd:
            head = f"Ran {n_cmd} command{'s' if n_cmd != 1 else ''}{where}."
        else:
            head = f"No file changes{where}."
    if facts.get("tests_ran"):
        failed = facts.get("tests_failed", 0)
        if failed:
            head += f" {failed} test{'s' if failed != 1 else ''} failing."
        else:
            head += " Tests ran clean."
    return head


def _cap(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    boundaries = list(re.finditer(r"[.!?](\s|$)", cut))
    if boundaries:
        return cut[: boundaries[-1].end()].strip()
    return cut.rstrip() + "…"


_PATH_RE = re.compile(r"\S*/\S+")


def _to_basename(match: re.Match[str]) -> str:
    token = match.group(0).rstrip(".,;:")
    base = token.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0] if "." in base else base


def speechify(text: str, max_chars: int) -> str:
    """Reduce markdown to plain spoken English, then cap on a sentence boundary."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)   # fenced code
    text = text.replace("`", "")                                    # inline code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)            # links -> label
    text = re.sub(r"^[\s>#*+-]+", "", text, flags=re.MULTILINE)      # list/quote/heading marks
    text = text.replace("*", "")  # bold/italic markers (keep _ for snake_case)
    text = _PATH_RE.sub(_to_basename, text)                         # paths -> basename
    text = text.replace("&", " and ").replace("->", " to ")
    text = re.sub(r"\s+", " ", text).strip()
    return _cap(text, max_chars)


def _llm_clause(last_message: str, cfg: dict[str, Any]) -> str | None:
    summary_cfg = cfg.get("summary", {})
    command = (summary_cfg.get("llm_command") or "").strip()
    message = (last_message or "").strip()
    if not command or not message:
        return None
    prompt = (
        "In ONE spoken sentence under 30 words, say what was done. Plain English, "
        "no markdown, no code, no file paths spelled out. Message:\n\n" + message
    )
    try:
        result = subprocess.run(
            shlex.split(command),
            input=prompt,
            capture_output=True,
            text=True,
            timeout=summary_cfg.get("llm_timeout_seconds", 8),
        )
    except (OSError, subprocess.SubprocessError):
        return None  # missing command, or timed out
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def summarize(
    facts: dict[str, Any],
    last_message: str,
    cfg: dict[str, Any],
    project: str | None = None,
) -> str:
    """Produce the final spoken string per ``summary.mode``, speech-safe and capped."""
    mode = cfg.get("summary", {}).get("mode", "hybrid")
    max_chars = cfg.get("speak", {}).get("max_chars", 240)
    facts_part = facts_sentence(facts, project=project)

    if mode == "facts":
        return _cap(facts_part, max_chars)

    clause = _llm_clause(last_message, cfg)
    if mode == "llm":
        return speechify(clause, max_chars) if clause else _cap(facts_part, max_chars)

    # hybrid: facts + optional LLM clause, falling back cleanly to facts-only
    if clause:
        return _cap(f"{facts_part} {speechify(clause, max_chars)}", max_chars)
    return _cap(facts_part, max_chars)
