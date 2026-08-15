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
from . import desktop, osutil, paths

# Package-manager install-command prefixes, tried in order — so hints match the
# user's distro instead of assuming Arch.
_MANAGERS: list[tuple[str, str]] = [
    ("pacman", "sudo pacman -S"),
    ("apt", "sudo apt install"),
    ("dnf", "sudo dnf install"),
    ("zypper", "sudo zypper install"),
    ("xbps-install", "sudo xbps-install -S"),
    ("apk", "sudo apk add"),
]

# Package names that differ from the binary name ("_" = the cross-distro default).
_PKG_NAMES: dict[str, dict[str, str]] = {
    "pw-record": {"pacman": "pipewire pipewire-audio", "apt": "pipewire-audio",
                  "dnf": "pipewire-utils", "_": "pipewire"},
    "wl-copy": {"_": "wl-clipboard"},
    "notify-send": {"apt": "libnotify-bin", "_": "libnotify"},
    "hyprctl": {"_": "hyprland"},
    "swaymsg": {"_": "sway"},
}

MODEL_MIN_BYTES = 100 * 1024 * 1024  # a real Whisper model is well over 100 MB


def _pkg_manager() -> tuple[str, str] | None:
    return next(((name, cmd) for name, cmd in _MANAGERS if shutil.which(name)), None)


def _install_hint(tool: str) -> str:
    """A distro-appropriate 'how to install <tool>' string. Falls back to a neutral
    'install <pkg>' when no known package manager is on PATH."""
    if osutil.IS_WINDOWS:
        for mgr in ("winget", "scoop", "choco"):
            if shutil.which(mgr):
                return f"{mgr} install {tool}"
        return f"install {tool}"
    if osutil.IS_MACOS:
        return f"brew install {tool}" if shutil.which("brew") else f"install {tool}"
    names = _PKG_NAMES.get(tool, {})
    mgr = _pkg_manager()
    if mgr:
        pkg = names.get(mgr[0]) or names.get("_") or tool
        return f"{mgr[1]} {pkg}"
    return f"install {names.get('_') or tool}"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""
    soft: bool = False  # advisory (e.g. optional Echo backends) — doesn't fail doctor


def _bin(name: str, hint: str, soft: bool = False) -> Check:
    path = shutil.which(name)
    if path:
        return Check(name, True, path)
    return Check(name, False, "not found on PATH", hint, soft=soft)


def _backend_check(be: str) -> Check:
    """Report the detected desktop backend and whether the pet is supported there.
    Only Hyprland is validated by the author; the rest ship experimental."""
    tested = be == desktop.HYPRLAND
    supported = be in (desktop.HYPRLAND, desktop.SWAY)
    bits = [be]
    if not tested:
        bits.append("experimental")
    if supported:
        bits.append("pet ✓")
    else:
        native = osutil.IS_WINDOWS or osutil.IS_MACOS
        bits.append("no pet (Linux/wlroots only)" if native else "no pet (needs Hyprland/Sway)")
    return Check("desktop", True, ", ".join(bits))


def _audio_input_check() -> Check:
    """A mic-capture tool must exist: pw-record/parec (PipeWire/PulseAudio) on Linux,
    or the sounddevice module (WASAPI on Windows, CoreAudio on macOS)."""
    if osutil.IS_WINDOWS or osutil.IS_MACOS:
        extra = "windows" if osutil.IS_WINDOWS else "macos"
        try:
            import sounddevice  # noqa: F401
        except Exception as exc:  # PortAudio or the module itself missing
            return Check("audio capture", False,
                         f"sounddevice unavailable ({type(exc).__name__})",
                         f"pip install voxpane[{extra}]")
        return Check("audio capture", True, "sounddevice")
    for tool in ("pw-record", "parec"):
        path = shutil.which(tool)
        if path:
            return Check("audio capture", True, f"{tool} ({path})")
    return Check("audio capture", False, "no pw-record or parec", _install_hint("pw-record"))


def _desktop_binaries(cfg: dict[str, Any], be: str) -> list[tuple[str, str, bool]]:
    """The focus/type/clipboard tools THIS desktop needs → (binary, hint, soft).

    The focus reader is advisory (its absence just relaxes the focus gate); the typing
    tool is required only in ``focus`` delivery mode (other modes fall back to the
    clipboard); the clipboard tool is always required — it is the universal fallback."""
    if be == desktop.WINDOWS:
        # Focus is read via ctypes (no binary); paste + clipboard go through PowerShell,
        # which ships with Windows. Required only in focus mode (else clipboard fallback).
        typer_soft = cfg["delivery"]["mode"] != "focus"
        return [("powershell", "ships with Windows — used for paste + clipboard", typer_soft)]

    if be == desktop.MACOS:
        # Focus + paste use osascript (AppleScript); clipboard uses pbcopy — both built in.
        typer_soft = cfg["delivery"]["mode"] != "focus"
        return [("osascript", "built into macOS — focus + paste", typer_soft),
                ("pbcopy", "built into macOS — clipboard", False)]

    focus = {desktop.HYPRLAND: "hyprctl", desktop.SWAY: "swaymsg", desktop.X11: "xdotool"}.get(be)
    typer = {desktop.HYPRLAND: "wtype", desktop.SWAY: "wtype",
             desktop.X11: "xdotool", desktop.WAYLAND: "ydotool"}.get(be, "")
    clip = "xclip" if be == desktop.X11 else "wl-copy"

    rows: list[tuple[str, str, bool]] = []
    if focus:
        rows.append((focus, _install_hint(focus) + " — the focus gate needs it", True))
    typer_soft = cfg["delivery"]["mode"] != "focus"
    if typer:
        rows.append((typer, _install_hint(typer) + " — types into the focused app", typer_soft))
    rows.append((clip, _install_hint(clip) + " — clipboard delivery + fallback", False))

    # X11 uses xdotool for both focus and typing; dedup, keeping the strictest (hard).
    merged: dict[str, tuple[str, bool]] = {}
    for name, hint, soft in rows:
        if name in merged:
            merged[name] = (merged[name][0], merged[name][1] and soft)
        else:
            merged[name] = (hint, soft)
    return [(name, hint, soft) for name, (hint, soft) in merged.items()]


def _stt(cfg: dict[str, Any]) -> Check:
    """STT is available if voxpaned is running OR whisper-cli + its model exist."""
    daemon_up = (paths.daemon_port_file().exists() if osutil.IS_WINDOWS
                 else paths.socket_path().is_socket())
    if daemon_up:
        return Check("speech-to-text", True, "voxpaned daemon (resident model)")
    binary = cfg["whisper"].get("binary", "whisper-cli")
    model = config_mod.model_path(cfg)
    have_model = model.exists() and model.stat().st_size >= MODEL_MIN_BYTES
    if shutil.which(binary) and have_model:
        return Check("speech-to-text", True, f"{binary} + {model.name}")
    return Check(
        "speech-to-text",
        False,
        "no daemon, and no whisper-cli + model",
        "start it: systemctl --user start voxpaned  (or install whisper.cpp + the model)",
    )


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
    be = desktop.backend(cfg)

    checks: list[Check] = [_backend_check(be)]
    checks.append(_audio_input_check())
    for name, hint, soft in _desktop_binaries(cfg, be):
        checks.append(_bin(name, hint, soft=soft))
    # The shell hooks (jq) run on Linux + macOS; Windows uses PowerShell hooks instead.
    if not osutil.IS_WINDOWS:
        checks.append(_bin("jq", _install_hint("jq") + " — the Claude Code hook scripts need it"))
    # notifications / pet / media-pause / Echo backends are Linux-desktop only.
    if osutil.IS_LINUX:
        checks.append(_bin("notify-send", _install_hint("notify-send") + " — desktop notifications",
                           soft=True))
        if desktop.overlay_supported(cfg):
            checks.append(_bin("eww", "build eww (github.com/elkowars/eww) — the pixel pet",
                               soft=True))
        checks.append(_bin("playerctl", _install_hint("playerctl") + " — pauses media on wake",
                           soft=True))
    checks.append(_stt(cfg))
    if osutil.IS_LINUX:  # wpctl / Echo backends are Linux-only
        checks.append(_default_source())
    checks.append(_runtime_dir_writable())
    checks.append(_tmux_target(cfg))
    if osutil.IS_LINUX:
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
