"""Integration tests for the gated speak-from-hook flow (M6)."""

from __future__ import annotations

import time

import pytest

from voxpane import cli, config, ledger, notify, paths


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Disable quiet hours (time-of-day independent) and pin facts-only summaries
    # so the flow never shells out to a real LLM during tests.
    cfg_dir = tmp_path / "voxpane"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(
        '[speak.gate]\nquiet_hours = ""\n\n[summary]\nmode = "facts"\n'
    )

    spoken: list[tuple[str, str]] = []

    def record(summary, body="", **kwargs):
        spoken.append((summary, body))

    monkeypatch.setattr(notify, "notify", record)
    return spoken


def _seed(session, n_files=4, seconds_ago=60):
    now = int(time.time())
    for i in range(n_files):
        ledger.append_from_payload(
            {"session_id": session, "ts": now - seconds_ago, "tool_name": "Edit",
             "tool_input": {"file_path": f"f{i}.py"}}
        )
    ledger.append_from_payload(
        {"session_id": session, "ts": now - seconds_ago + 1, "tool_name": "Bash",
         "tool_input": {"command": "uv run pytest"}, "tool_response": {"exit_code": 0}}
    )


def test_speaks_factual_summary_on_real_work(_iso):
    _seed("s")
    payload = {"session_id": "s", "last_assistant_message": "Updated the parser."}
    rc = cli._speak_from_hook(payload, config.load())
    assert rc == 0
    assert len(_iso) == 1
    _, body = _iso[0]
    assert "file" in body and "Tests ran clean" in body
    assert not paths.ledger_file("s").exists()  # truncated after summarising


def test_silent_when_turn_ends_in_question(_iso):
    _seed("s")
    payload = {"session_id": "s", "last_assistant_message": "Which file should I edit?"}
    rc = cli._speak_from_hook(payload, config.load())
    assert rc == 0
    assert _iso == []
    assert not paths.ledger_file("s").exists()


def test_silent_on_short_turn(_iso):
    now = int(time.time())
    ledger.append_from_payload(
        {"session_id": "s", "ts": now - 3, "tool_name": "Edit", "tool_input": {"file_path": "a.py"}}
    )
    payload = {"session_id": "s", "last_assistant_message": "Fixed it."}
    rc = cli._speak_from_hook(payload, config.load())
    assert rc == 0
    assert _iso == []


def test_silent_without_tool_use(_iso):
    payload = {"session_id": "empty", "last_assistant_message": "Some prose."}
    rc = cli._speak_from_hook(payload, config.load())
    assert rc == 0
    assert _iso == []
