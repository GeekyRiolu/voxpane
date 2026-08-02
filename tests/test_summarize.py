"""Tests for the summarizer and speech post-processing (M7)."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from voxpane import summarize

FACTS = {"n_files": 3, "n_commands": 1, "tests_ran": 1, "tests_failed": 0}


def _cfg(mode="hybrid", llm_command="claude -p", max_chars=240, timeout=8):
    return {
        "summary": {"mode": mode, "llm_command": llm_command, "llm_timeout_seconds": timeout},
        "speak": {"max_chars": max_chars},
    }


# --- speechify: markdown -> plain spoken English ---

def test_speechify_strips_code_fence():
    md = "Refactored the parser.\n```python\nprint('hi')\n```\nAll green."
    out = summarize.speechify(md, 240)
    assert "`" not in out and "print" not in out
    assert "Refactored the parser." in out


def test_speechify_strips_bullets_and_emphasis():
    md = "- Fixed **auth**\n- Added *tests*\n- Bumped version"
    out = summarize.speechify(md, 240)
    assert "*" not in out
    assert "-" not in out.split()  # no bare list marker survives
    assert "Fixed auth" in out and "Added tests" in out


def test_speechify_collapses_paths_to_basename():
    out = summarize.speechify("Edited src/voxpane/cli.py and tests/test_gate.py", 240)
    assert "/" not in out and ".py" not in out
    assert "cli" in out and "test_gate" in out


def test_speechify_caps_on_sentence_boundary():
    md = "First sentence here. Second sentence follows. Third one too."
    out = summarize.speechify(md, 30)
    assert len(out) <= 30
    assert out.endswith((".", "…"))


# --- summarize modes ---

def test_facts_mode_ignores_llm():
    out = summarize.summarize(FACTS, "irrelevant **markdown**", _cfg(mode="facts"))
    assert out == "3 files changed. Tests ran clean."


def test_hybrid_falls_back_to_facts_without_llm_command():
    out = summarize.summarize(FACTS, "did stuff", _cfg(mode="hybrid", llm_command=""))
    assert out == "3 files changed. Tests ran clean."


def test_hybrid_combines_facts_and_llm_clause(monkeypatch):
    monkeypatch.setattr(summarize, "_llm_clause", lambda msg, cfg: "Tidied the `parser` module.")
    out = summarize.summarize(FACTS, "Tidied the parser.", _cfg(mode="hybrid"))
    assert out.startswith("3 files changed. Tests ran clean.")
    assert "Tidied the parser module." in out
    assert "`" not in out


def test_hybrid_falls_back_cleanly_on_timeout(monkeypatch):
    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(summarize.subprocess, "run", boom)
    out = summarize.summarize(FACTS, "message", _cfg(mode="hybrid"))
    assert out == "3 files changed. Tests ran clean."


def test_llm_clause_marks_nested_claude_against_recursion(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["env"] = kwargs.get("env")
        return SimpleNamespace(returncode=0, stdout="did stuff", stderr="")

    monkeypatch.setattr(summarize.subprocess, "run", fake_run)
    cfg = {"summary": {"llm_command": "claude -p", "llm_timeout_seconds": 8}}
    assert summarize._llm_clause("a message", cfg) == "did stuff"
    assert seen["env"]["VOXPANE_NO_HOOK"] == "1"  # nested Claude won't re-fire hooks


def test_llm_mode_uses_clause(monkeypatch):
    monkeypatch.setattr(summarize, "_llm_clause", lambda msg, cfg: "Cleaned up imports.")
    out = summarize.summarize(FACTS, "msg", _cfg(mode="llm"))
    assert out == "Cleaned up imports."


def test_long_summary_capped_under_max_chars():
    facts = {"n_files": 2, "tests_ran": 0}
    long_msg = "word " * 200
    out = summarize.summarize(facts, long_msg, _cfg(mode="facts", max_chars=60))
    assert len(out) <= 60
