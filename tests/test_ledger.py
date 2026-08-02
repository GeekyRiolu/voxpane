"""Tests for the activity ledger and facts reduction (M6)."""

from __future__ import annotations

import pytest

from voxpane import ledger, paths, summarize


@pytest.fixture(autouse=True)
def _runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))


def test_append_and_read_roundtrip():
    ledger.append_from_payload(
        {"session_id": "s", "tool_name": "Edit", "tool_input": {"file_path": "a.py"}}
    )
    ledger.append_from_payload(
        {
            "session_id": "s",
            "tool_name": "Bash",
            "tool_input": {"command": "uv run pytest"},
            "tool_response": {"exit_code": 0},
        }
    )
    entries = ledger.read("s")
    assert [e.tool for e in entries] == ["Edit", "Bash"]
    assert entries[0].path == "a.py"
    assert entries[1].cmd == "uv run pytest" and entries[1].exit == 0


def test_facts_counts_files_commands_and_tests():
    for payload in [
        {"session_id": "s", "tool_name": "Edit", "tool_input": {"file_path": "a.py"}},
        {"session_id": "s", "tool_name": "Edit", "tool_input": {"file_path": "a.py"}},  # dup
        {"session_id": "s", "tool_name": "Write", "tool_input": {"file_path": "b.py"}},
        {
            "session_id": "s",
            "tool_name": "Bash",
            "tool_input": {"command": "uv run pytest"},
            "tool_response": {"exit_code": 0},
        },
    ]:
        ledger.append_from_payload(payload)

    f = ledger.facts(ledger.read("s"))
    assert f["n_files"] == 2  # a.py deduped
    assert f["n_commands"] == 1
    assert f["tests_ran"] == 1 and f["tests_failed"] == 0


def test_facts_detects_failing_tests():
    ledger.append_from_payload(
        {
            "session_id": "s",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest -x"},
            "tool_response": {"exit_code": 1},
        }
    )
    f = ledger.facts(ledger.read("s"))
    assert f["tests_ran"] == 1 and f["tests_failed"] == 1


def test_truncate_and_active_sessions():
    ledger.append_from_payload(
        {"session_id": "one", "tool_name": "Edit", "tool_input": {"file_path": "x"}}
    )
    ledger.append_from_payload(
        {"session_id": "two", "tool_name": "Edit", "tool_input": {"file_path": "y"}}
    )
    assert ledger.active_sessions() == 2
    ledger.truncate("one")
    assert ledger.active_sessions() == 1
    assert not paths.ledger_file("one").exists()


def test_facts_sentence_reads_naturally():
    f = ledger.facts(
        [
            ledger.Entry(ts=1, tool="Edit", path="a.py"),
            ledger.Entry(ts=2, tool="Write", path="b.py"),
        ]
    )
    assert summarize.facts_sentence(f, project="voxpane") == "2 files changed in voxpane."

    with_tests = dict(f, tests_ran=1, tests_failed=0)
    assert summarize.facts_sentence(with_tests).endswith("Tests ran clean.")
