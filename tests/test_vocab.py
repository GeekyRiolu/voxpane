"""Tests for `voxpane vocab --from-repo` (M9)."""

from __future__ import annotations

from voxpane import vocab


def test_splits_camel_and_snake_case():
    files = ["src/voxpane/postProcess.py", "tests/test_gate.py", "config/config.default.toml"]
    words = vocab.from_repo(ls_files=files).split(", ")
    assert "post" in words and "process" in words  # camelCase split
    assert "gate" in words  # snake_case split
    assert "config" in words


def test_filters_stopwords_and_extensions():
    words = vocab.from_repo(ls_files=["src/main.py", "README.md"]).split(", ")
    assert "py" not in words and "md" not in words
    assert "main" not in words and "readme" not in words  # stopwords


def test_orders_by_frequency_and_caps():
    files = ["auth.py", "authHandler.py", "auth_service.py", "widget.py"]
    words = vocab.from_repo(ls_files=files, cap_tokens=2).split(", ")
    assert len(words) == 2
    assert words[0] == "auth"  # most frequent first


def test_empty_repo_yields_empty_string():
    assert vocab.from_repo(ls_files=[]) == ""
