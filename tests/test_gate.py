"""Tests for the outbound gate (M6) — where the annoyance lives."""

from __future__ import annotations

from datetime import time as dt_time

from voxpane import gate

GATE = {
    "min_turn_seconds": 25,
    "require_tool_use": True,
    "skip_if_question": True,
    "quiet_hours": "23:00-08:00",
}


def _should(**over):
    kw = {
        "turn_seconds": 60,
        "has_tool_use": True,
        "last_message": "Done. Edited the parser.",
        "now": dt_time(14, 0),
        "gate_cfg": GATE,
    }
    kw.update(over)
    return gate.should_speak(**kw)


def test_speaks_on_real_work():
    ok, _ = _should()
    assert ok is True


def test_silent_without_tool_use():
    ok, reason = _should(has_tool_use=False)
    assert ok is False and "tool" in reason


def test_silent_on_short_turn():
    ok, reason = _should(turn_seconds=5)
    assert ok is False and "short" in reason


def test_silent_when_ends_in_question():
    ok, reason = _should(last_message="Which file should I edit?")
    assert ok is False and "question" in reason


def test_silent_during_quiet_hours():
    ok, reason = _should(now=dt_time(2, 30))
    assert ok is False and "quiet" in reason


def test_quiet_hours_wrap_midnight():
    assert gate.in_quiet_hours(dt_time(23, 30), "23:00-08:00") is True
    assert gate.in_quiet_hours(dt_time(7, 0), "23:00-08:00") is True
    assert gate.in_quiet_hours(dt_time(12, 0), "23:00-08:00") is False


def test_quiet_hours_same_day_window():
    assert gate.in_quiet_hours(dt_time(13, 0), "12:00-14:00") is True
    assert gate.in_quiet_hours(dt_time(15, 0), "12:00-14:00") is False


def test_is_question_ignores_code_and_lists():
    assert gate.is_question("Shall I proceed?") is True
    assert gate.is_question("Here is the diff:\n```\ncode?\n```") is False
    assert gate.is_question("- a bullet point?") is False
    assert gate.is_question("") is False
