"""Load and merge voxpane configuration.

The canonical, fully-commented defaults live in ``config/config.default.toml``
(installed to ``~/.config/voxpane/config.toml`` by ``install.sh``). At runtime we
load that default file, then deep-merge the user's config on top so a partial
user config only overrides the keys it sets.

``_SAFETY_DEFAULTS`` is a last-resort fallback used only if the packaged default
file cannot be located (e.g. an unusual install layout). It must stay a superset
of the keys the CLI reads before a user config exists — chiefly what ``doctor``
needs. ``tests/test_config.py`` asserts it stays in sync with the TOML.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from . import paths

_SAFETY_DEFAULTS: dict[str, Any] = {
    "audio": {"source": "default", "rate": 16000, "max_seconds": 120},
    "whisper": {
        "binary": "whisper-cli",
        "model": "~/.local/share/whisper-models/ggml-large-v3-turbo-q5_0.bin",
        "daemon_model": "large-v3-turbo",
        "language": "en",
        "threads": 0,
        "initial_prompt": "",
    },
    "delivery": {
        "mode": "tmux",
        "tmux_target": "claude:0.0",
        "auto_submit": False,
        "focus_paste_delay_ms": 80,
    },
    "behavior": {"strip_filler": True, "trailing_submit_phrase": "send it"},
    "listen": {
        "enabled": True,
        "endpoint_silence_ms": 1500,
        "min_speech_ms": 300,
        "max_utterance_seconds": 30,
        "vad_aggressiveness": 2,
        "auto_submit": True,
        "conversational": True,
        "post_speak_guard_ms": 700,
        "barge_in": False,
        "stop_words": ["stop", "stop it", "enough", "cancel", "never mind"],
        "focus_only": True,
        "focus_poll_ms": 250,
        "focus_match": "",
        "pause_on_playback": True,
    },
    "speak": {
        "enabled": True,
        "backends": ["alexa", "bluetooth", "notify"],
        "max_chars": 240,
        "prefix_project": "auto",
        "gate": {
            "min_turn_seconds": 25,
            "require_tool_use": True,
            "skip_if_question": True,
            "quiet_hours": "23:00-08:00",
        },
        "alexa": {"command": "alexa", "device": "", "mode": "say"},
        "bluetooth": {"sink": "", "piper_model": "", "lead_silence_ms": 800},
    },
    "summary": {
        "mode": "hybrid",
        "llm_command": "claude -p --model haiku --output-format text",
        "llm_timeout_seconds": 8,
    },
}


def _default_toml_path() -> Path | None:
    """Locate the packaged ``config.default.toml`` across install layouts."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "config" / "config.default.toml",  # from-source / editable
        here.parent / "data" / "config.default.toml",         # wheel package data
    ]
    return next((c for c in candidates if c.is_file()), None)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def defaults() -> dict[str, Any]:
    """Return the shipped default configuration."""
    path = _default_toml_path()
    if path is not None:
        return tomllib.loads(path.read_text())
    return _SAFETY_DEFAULTS


def load(path: Path | None = None) -> dict[str, Any]:
    """Return the effective config: user file deep-merged over the defaults."""
    base = defaults()
    config_path = path or paths.config_file()
    if config_path.is_file():
        user = tomllib.loads(config_path.read_text())
        return _deep_merge(base, user)
    return base


def model_path(cfg: dict[str, Any]) -> Path:
    """Resolve ``whisper.model`` to an absolute, ~-expanded path."""
    return Path(cfg["whisper"]["model"]).expanduser()


def _default_commands_path() -> Path | None:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "config" / "commands.default.toml",
        here.parent / "data" / "commands.default.toml",
    ]
    return next((c for c in candidates if c.is_file()), None)


def default_commands() -> dict[str, Any]:
    """Return the shipped command dictionary (text/keys/transforms/fixups)."""
    path = _default_commands_path()
    return tomllib.loads(path.read_text()) if path is not None else {}


def load_commands(path: Path | None = None) -> dict[str, Any]:
    """Return the effective command dictionary: user file merged over defaults."""
    base = default_commands()
    commands_path = path or paths.commands_file()
    if commands_path.is_file():
        return _deep_merge(base, tomllib.loads(commands_path.read_text()))
    return base
