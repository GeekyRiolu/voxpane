"""Build a per-project vocabulary prompt from the repo — milestone M9.

Scans ``git ls-files``, splits identifiers (camelCase / snake_case / kebab /
dotted) into words, and emits a comma-separated addendum for
``whisper.initial_prompt``, ordered by frequency and capped near the 224-token
limit so the decoder is biased toward this project's names.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+")
_STOP = {
    "the", "and", "for", "src", "lib", "test", "tests", "init", "main", "index",
    "app", "core", "utils", "common", "py", "js", "ts", "tsx", "jsx", "md", "txt",
    "json", "toml", "yaml", "yml", "cfg", "ini", "png", "jpg", "svg", "lock",
    "git", "github", "node", "modules", "dist", "build", "www", "readme",
}


def _split(name: str) -> list[str]:
    words: list[str] = []
    for part in re.split(r"[^A-Za-z0-9]+", name):
        words += _CAMEL.findall(part)
    return [w.lower() for w in words if len(w) > 2]


def _git_ls_files(root: Path | None) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root or Path.cwd()),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return result.stdout.splitlines() if result.returncode == 0 else []


def from_repo(
    root: Path | None = None,
    cap_tokens: int = 224,
    ls_files: list[str] | None = None,
) -> str:
    """Return a comma-separated vocabulary addendum, most frequent words first."""
    files = ls_files if ls_files is not None else _git_ls_files(root)
    counter: Counter[str] = Counter()
    for path in files:
        for word in _split(Path(path).name):
            if word not in _STOP:
                counter[word] += 1
    return ", ".join(word for word, _ in counter.most_common(cap_tokens))
