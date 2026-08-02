"""Filesystem locations for voxpane, following the XDG Base Directory spec.

  config   ~/.config/voxpane/                 config.toml, commands.toml
  state    ~/.local/state/voxpane/            log
  data     ~/.local/share/voxpane/            (reserved)
  runtime  $XDG_RUNTIME_DIR/voxpane/          state.json, record.pid, socket,
                                              ledger-<session_id>.jsonl

Runtime state is deliberately volatile: it lives in a tmpfs that is wiped on
logout, which is exactly what we want for PIDs, sockets and per-session ledgers.
"""

from __future__ import annotations

import os
from pathlib import Path

APP = "voxpane"


def _xdg(var: str, default: Path) -> Path:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else default


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / APP


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / APP


def runtime_dir() -> Path:
    """Volatile per-login runtime directory.

    ``XDG_RUNTIME_DIR`` is normally set by the session manager; fall back to a
    uid-scoped path under ``/tmp`` for headless or cron contexts where it is not.
    """
    rt = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(rt) if rt else Path(f"/tmp/user-{os.getuid()}")
    return base / APP


def config_file() -> Path:
    return config_dir() / "config.toml"


def commands_file() -> Path:
    return config_dir() / "commands.toml"


def log_file() -> Path:
    return state_dir() / "log"


def state_file() -> Path:
    return runtime_dir() / "state.json"


def socket_path() -> Path:
    return runtime_dir() / "daemon.sock"


def record_pid_file() -> Path:
    return runtime_dir() / "record.pid"


def record_state_file() -> Path:
    """Tracks the in-flight recording (wav path, pid, start time) so `stop`
    knows what `start` began."""
    return runtime_dir() / "record.json"


def ledger_file(session_id: str) -> Path:
    # Guard against a session_id that contains path separators.
    safe = session_id.replace("/", "_").replace("..", "_") or "default"
    return runtime_dir() / f"ledger-{safe}.jsonl"


def speak_lock_file() -> Path:
    """Single lock serialising concurrent utterances across sessions."""
    return runtime_dir() / "speak.lock"


def speaking_marker() -> Path:
    """Present while a summary is being spoken (drives the waybar speaker icon)."""
    return runtime_dir() / "speaking"


def listener_pid_file() -> Path:
    """PID of the hands-free `voxpane listen` loop."""
    return runtime_dir() / "listen.pid"


def listen_sessions_file() -> Path:
    """Set of active Claude session ids keeping the listener alive (ref-count)."""
    return runtime_dir() / "listen-sessions"


def play_pid_file() -> Path:
    """PID of the in-progress TTS playback, so `voxpane hush` can stop it."""
    return runtime_dir() / "play.pid"


def ensure(directory: Path) -> Path:
    """Create ``directory`` (and parents) if missing, then return it."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory
