"""The activity ledger — milestone M6.

``PostToolUse`` hooks append one JSON line per tool call to
``$XDG_RUNTIME_DIR/voxpane/ledger-<session_id>.jsonl``::

    {"ts": 1754130000, "tool": "Edit",  "path": "src/voxpane/cli.py"}
    {"ts": 1754130012, "tool": "Bash",  "cmd": "uv run pytest", "exit": 0}

Facts beat prose: "Four files changed, tests ran clean" is derived
deterministically from this and is more useful spoken aloud than any summary of
Claude's markdown. The ledger is truncated at Stop, after the summary is built.

For speed, ``hooks/voxpane-post-tool.sh`` appends with ``jq`` directly; this
module owns reading/reducing/pruning and keeps the write path available to
``voxpane ledger append --from-hook`` for parity and testing.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from . import paths

# Substrings (space-padded) that mark a command as a test run.
_TEST_HINTS = (
    "pytest", "npm test", "npm run test", "go test", "cargo test",
    "jest", "vitest", "unittest", "make test", " test ",
)


@dataclass(frozen=True)
class Entry:
    ts: int
    tool: str
    path: str | None = None
    cmd: str | None = None
    exit: int | None = None


def _entry_from_payload(payload: dict[str, Any]) -> Entry:
    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}
    return Entry(
        ts=int(payload.get("ts") or time.time()),
        tool=payload.get("tool_name", "?"),
        path=tool_input.get("file_path"),
        cmd=tool_input.get("command"),
        exit=tool_response.get("exit_code"),
    )


def append_from_payload(payload: dict[str, Any]) -> None:
    session = payload.get("session_id", "default")
    entry = _entry_from_payload(payload)
    paths.ensure(paths.runtime_dir())
    line = {k: v for k, v in entry.__dict__.items() if v is not None}
    with paths.ledger_file(session).open("a") as fh:
        fh.write(json.dumps(line) + "\n")


def read(session_id: str) -> list[Entry]:
    ledger = paths.ledger_file(session_id)
    if not ledger.is_file():
        return []
    entries: list[Entry] = []
    for raw in ledger.read_text().splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
            entries.append(
                Entry(
                    ts=int(d.get("ts", 0)),
                    tool=d.get("tool", "?"),
                    path=d.get("path"),
                    cmd=d.get("cmd"),
                    exit=d.get("exit"),
                )
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return entries


def _looks_like_test(cmd: str) -> bool:
    padded = f" {cmd.lower()} "
    return any(hint in padded for hint in _TEST_HINTS)


def facts(entries: list[Entry]) -> dict[str, Any]:
    """Reduce entries to the counters the summariser templates from."""
    files = sorted({e.path for e in entries if e.path})
    commands = [e for e in entries if e.cmd]
    tests = [e for e in commands if _looks_like_test(e.cmd or "")]
    tests_failed = [e for e in tests if e.exit not in (None, 0)]
    return {
        "n_tools": len(entries),
        "files": files,
        "n_files": len(files),
        "n_commands": len(commands),
        "tests_ran": len(tests),
        "tests_failed": len(tests_failed),
        "first_ts": min((e.ts for e in entries), default=None),
        "last_ts": max((e.ts for e in entries), default=None),
        "tools": dict(Counter(e.tool for e in entries)),
    }


def truncate(session_id: str) -> None:
    """Clear a session's ledger (called at Stop, after the summary is built)."""
    try:
        paths.ledger_file(session_id).unlink()
    except FileNotFoundError:
        pass


def active_sessions() -> int:
    rt = paths.runtime_dir()
    return len(list(rt.glob("ledger-*.jsonl"))) if rt.is_dir() else 0
