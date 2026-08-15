"""Filesystem locations for voxpane, following the XDG Base Directory spec.

  config   ~/.config/voxpane/                 config.toml, commands.toml
  state    ~/.local/state/voxpane/            log
  data     ~/.local/share/voxpane/            (reserved)
  runtime  $XDG_RUNTIME_DIR/voxpane/          state.json, record.pid, socket,
                                              ledger-<session_id>.jsonl

On POSIX, runtime state is deliberately volatile: it lives in a tmpfs wiped on
logout, which is exactly what we want for PIDs, sockets and per-session ledgers.
Windows has no such tmpfs, so there runtime state is a stable per-user directory
under ``%LOCALAPPDATA%`` (and config/data map to ``%APPDATA%``/``%LOCALAPPDATA%``).
"""

from __future__ import annotations

import os
from pathlib import Path

from . import osutil

APP = "voxpane"


def _env_path(var: str) -> Path | None:
    value = os.environ.get(var)
    return Path(value).expanduser() if value else None


def _xdg(var: str, default: Path) -> Path:
    return _env_path(var) or default


def _win_local() -> Path:
    return _env_path("LOCALAPPDATA") or Path.home() / "AppData" / "Local"


def config_dir() -> Path:
    if osutil.IS_WINDOWS:
        return (_env_path("APPDATA") or Path.home() / "AppData" / "Roaming") / APP
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / APP


def state_dir() -> Path:
    if osutil.IS_WINDOWS:
        return _win_local() / APP / "state"
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP


def data_dir() -> Path:
    if osutil.IS_WINDOWS:
        return _win_local() / APP
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / APP


def runtime_dir() -> Path:
    """Per-login runtime directory (PIDs, sockets, per-session ledgers).

    POSIX: ``XDG_RUNTIME_DIR`` (a tmpfs wiped on logout), falling back to a
    uid-scoped ``/tmp`` path for headless/cron contexts. Windows: no tmpfs
    equivalent, so a stable per-user directory under ``%LOCALAPPDATA%``.
    """
    if osutil.IS_WINDOWS:
        return _win_local() / APP / "runtime"
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


def listen_windows_file() -> Path:
    """Per-session focused-window info; the listener only listens when one is
    focused (so it ignores YouTube, calls, other apps)."""
    return runtime_dir() / "listen-windows.json"


def overlay_state_file() -> Path:
    """Drives the on-screen Siri-style overlay: {state, text}."""
    return runtime_dir() / "overlay.json"


def ensure(directory: Path) -> Path:
    """Create ``directory`` (and parents) if missing, then return it."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory
