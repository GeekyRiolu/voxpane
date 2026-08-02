"""The activity ledger — milestone M6.

``PostToolUse`` hooks append one JSON line per tool call to
``$XDG_RUNTIME_DIR/voxpane/ledger-<session_id>.jsonl``::

    {"ts": 1754130000, "tool": "Edit",  "path": "src/voxpane/cli.py"}
    {"ts": 1754130012, "tool": "Bash",  "cmd": "uv run pytest", "exit": 0}
    {"ts": 1754130044, "tool": "Write", "path": "tests/test_postprocess.py"}

Facts beat prose: "Edited four files and ran the tests, all passing" is derived
deterministically from this and is more useful spoken aloud than any summary of
Claude's markdown. The ledger is truncated at Stop, after the summary is built.

For speed, ``hooks/voxpane-post-tool.sh`` appends with ``jq`` directly; this
module owns reading/summarising/pruning and keeps the write path available to
``voxpane ledger append --from-hook`` for parity and testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Entry:
    ts: int
    tool: str
    path: str | None = None
    cmd: str | None = None
    exit: int | None = None


def append_from_payload(payload: dict[str, Any]) -> None:
    """Append one entry derived from a PostToolUse hook payload."""
    raise NotImplementedError("ledger.append_from_payload — milestone M6")


def read(session_id: str) -> list[Entry]:
    """Read all entries for a session (empty list if the ledger is absent)."""
    raise NotImplementedError("ledger.read — milestone M6")


def facts(entries: list[Entry]) -> dict[str, Any]:
    """Reduce entries to counters the summariser templates from (files changed,
    commands run, tests passed/failed, …)."""
    raise NotImplementedError("ledger.facts — milestone M6")


def truncate(session_id: str) -> None:
    """Clear a session's ledger (called at Stop, after the summary is built)."""
    raise NotImplementedError("ledger.truncate — milestone M6")
