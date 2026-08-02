"""``voxpane doctor`` — verify the environment is ready.

This is milestone M0 and the reference implementation for the code style the
remaining milestones should follow: pure-ish check functions returning simple
data, a thin renderer, and a non-zero exit on failure.

Each check returns a :class:`Check`. Later milestones extend the list (Alexa
auth reachability, bluez sink presence) — add checks, don't restructure.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import config as config_mod
from . import paths

# Binaries the inbound path relies on, with the package that provides each and a
# short remediation hint used when it is missing.
_REQUIRED_BINARIES: list[tuple[str, str]] = [
    ("pw-record", "install pipewire (pacman -S pipewire pipewire-audio)"),
    ("whisper-cli", "install whisper.cpp (yay -S whisper.cpp)"),
    ("wtype", "install wtype (pacman -S wtype) — xdotool will NOT work on Wayland"),
    ("wl-copy", "install wl-clipboard (pacman -S wl-clipboard)"),
    ("tmux", "install tmux (pacman -S tmux)"),
    ("notify-send", "install libnotify (pacman -S libnotify)"),
    ("jq", "install jq (pacman -S jq) — the hook scripts need it"),
]

MODEL_MIN_BYTES = 100 * 1024 * 1024  # a real Whisper model is well over 100 MB


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""
    soft: bool = False  # advisory (e.g. optional Echo backends) — doesn't fail doctor


def _bin(name: str, hint: str) -> Check:
    path = shutil.which(name)
    if path:
        return Check(name, True, path)
    return Check(name, False, "not found on PATH", hint)


def _model(cfg: dict[str, Any]) -> Check:
    model = config_mod.model_path(cfg)
    if not model.exists():
        return Check(
            "whisper model",
            False,
            f"missing: {model}",
            "download it (see docs/INSTALL.md §1.4)",
        )
    size = model.stat().st_size
    if size < MODEL_MIN_BYTES:
        return Check(
            "whisper model",
            False,
            f"{model} is only {size // (1024 * 1024)} MB — looks truncated",
            "re-download the model",
        )
    return Check("whisper model", True, f"{model.name} ({size // (1024 * 1024)} MB)")


def _runtime_dir_writable() -> Check:
    rt = paths.runtime_dir()
    try:
        paths.ensure(rt)
        probe = rt / ".doctor-probe"
        probe.write_text("ok")
        probe.unlink()
        return Check("runtime dir", True, str(rt))
    except OSError as exc:
        return Check("runtime dir", False, f"{rt}: {exc}", "check XDG_RUNTIME_DIR")


def _default_source() -> Check:
    """Best-effort check that a default audio source exists and is unmuted."""
    if not shutil.which("wpctl"):
        return Check("audio source", True, "wpctl absent — skipping (informational)")
    try:
        out = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("audio source", False, str(exc), "check your microphone")
    if out.returncode != 0:
        return Check(
            "audio source",
            False,
            "no default source",
            "set one with wpctl or your audio panel",
        )
    muted = "MUTED" in out.stdout
    return Check(
        "audio source",
        not muted,
        out.stdout.strip() or "present",
        "unmute with wpctl set-mute @DEFAULT_AUDIO_SOURCE@ 0" if muted else "",
    )


def _alexa_check(cfg: dict[str, Any]) -> Check:
    if "alexa" not in cfg["speak"]["backends"]:
        return Check("alexa", True, "not in speak.backends — skipping")
    command = cfg["speak"]["alexa"].get("command", "alexa")
    if not shutil.which(command):
        return Check(
            "alexa", False, f"{command} not found",
            "uv tool install alexa-cli, then `alexa login`", soft=True,
        )
    try:
        result = subprocess.run([command, "devices"], capture_output=True, text=True, timeout=6)
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("alexa", False, str(exc), "check alexa-cli auth", soft=True)
    if result.returncode != 0:
        return Check("alexa", False, "devices call failed", "run `alexa login`", soft=True)
    return Check("alexa", True, "authed; devices reachable")


def _bluez_check(cfg: dict[str, Any]) -> Check:
    if "bluetooth" not in cfg["speak"]["backends"]:
        return Check("bluez sink", True, "not in speak.backends — skipping")
    if not shutil.which("pactl"):
        return Check("bluez sink", True, "pactl absent — skipping")
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("bluez sink", False, str(exc), "", soft=True)
    if "bluez_output." in result.stdout:
        return Check("bluez sink", True, "bluez sink present")
    return Check(
        "bluez sink", False, "no bluez_output.* sink",
        "pair & connect the Dot (docs/INSTALL.md §5)", soft=True,
    )


def _tmux_target(cfg: dict[str, Any]) -> Check:
    if cfg["delivery"]["mode"] != "tmux":
        return Check("tmux target", True, "delivery mode is not tmux — skipping")
    target = cfg["delivery"]["tmux_target"]
    if not shutil.which("tmux"):
        return Check("tmux target", False, "tmux missing", "install tmux")
    session = target.split(":", 1)[0]
    result = subprocess.run(
        ["tmux", "has-session", "-t", session],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Check("tmux target", True, f"session '{session}' exists")
    return Check(
        "tmux target",
        False,
        f"session '{session}' not found",
        f"start it: tmux new-session -s {session}",
    )


def run_checks(cfg: dict[str, Any] | None = None) -> list[Check]:
    cfg = cfg or config_mod.load()
    checks: list[Check] = [_bin(name, hint) for name, hint in _REQUIRED_BINARIES]
    checks.append(_model(cfg))
    checks.append(_default_source())
    checks.append(_runtime_dir_writable())
    checks.append(_tmux_target(cfg))
    checks.append(_alexa_check(cfg))
    checks.append(_bluez_check(cfg))
    return checks


def render(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = []
    for c in checks:
        mark = "✓" if c.ok else ("!" if c.soft else "✗")
        row = f"  {mark}  {c.name.ljust(width)}  {c.detail}"
        if not c.ok and c.hint:
            row += f"\n       ↳ {c.hint}"
        lines.append(row)
    return "\n".join(lines)


def main(cfg: dict[str, Any] | None = None, printer: Callable[[str], None] = print) -> int:
    checks = run_checks(cfg)
    printer("voxpane doctor\n")
    printer(render(checks))
    printer("")
    hard = [c for c in checks if not c.ok and not c.soft]
    soft = [c for c in checks if not c.ok and c.soft]
    if hard:
        printer(f"{len(hard)} check(s) failed. See hints above.")
        return 1
    if soft:
        printer(f"All required checks passed ({len(soft)} advisory — outbound/Echo).")
        return 0
    printer("All checks passed.")
    return 0
