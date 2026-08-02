"""The outbound gate — decide whether a finished turn is worth speaking (M6).

Pure and unit-tested: this is where the annoyance lives, so this is where the
tests concentrate. The Stop hook fires on *every* turn end; a turn is spoken only
if it did real work, ran long enough, didn't end in a question to the user, and
isn't inside quiet hours.
"""

from __future__ import annotations

from datetime import time as dt_time
from typing import Any


def _parse_hm(value: str) -> dt_time | None:
    try:
        hh, mm = value.strip().split(":", 1)
        return dt_time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(now: dt_time, spec: str) -> bool:
    if not spec or "-" not in spec:
        return False
    start_s, end_s = spec.split("-", 1)
    start, end = _parse_hm(start_s), _parse_hm(end_s)
    if start is None or end is None:
        return False
    if start <= end:
        return start <= now < end
    return now >= start or now < end  # window wraps past midnight


def is_question(message: str) -> bool:
    """True if the assistant's last line reads as a question to the user."""
    lines = [ln.strip() for ln in (message or "").splitlines() if ln.strip()]
    if not lines:
        return False
    last = lines[-1]
    if last.startswith(("```", "|", "-", "*")):  # code fence / table / list row
        return False
    return last.endswith("?")


def should_speak(
    *,
    turn_seconds: float,
    has_tool_use: bool,
    last_message: str,
    now: dt_time,
    gate_cfg: dict[str, Any],
) -> tuple[bool, str]:
    """Return (speak?, reason). The reason is for logging, not the user."""
    if gate_cfg.get("require_tool_use", True) and not has_tool_use:
        return False, "no tool use"
    min_s = gate_cfg.get("min_turn_seconds", 0)
    if turn_seconds < min_s:
        return False, f"too short ({turn_seconds:.0f}s < {min_s}s)"
    if gate_cfg.get("skip_if_question", True) and is_question(last_message):
        return False, "ends in a question"
    if in_quiet_hours(now, gate_cfg.get("quiet_hours", "")):
        return False, "quiet hours"
    return True, "ok"
