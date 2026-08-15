"""Desktop-integration backends — the compositor-specific glue.

voxpane's core is desktop-agnostic (PipeWire audio, ``playerctl``, ``notify-send``,
tmux/clipboard delivery). Only three things differ per desktop: reading the focused
window, injecting the paste keystroke, and copying to the clipboard. This module
detects the session and dispatches those to the right tool, so the rest of the code
stays neutral.

Backends: ``hyprland`` + ``sway`` (wlroots/Wayland) and ``x11`` are fully wired;
``wayland`` (generic — GNOME/KDE) is best-effort — there is no reliable focused-window
CLI there, so the focus gate simply relaxes and typing needs ``ydotool``. ``windows``
(native Win32, Phase 2) reads focus via ctypes and pastes/copies via PowerShell.
Detection is by environment (``sys.platform`` first, then the session); ``[desktop]
backend`` in config overrides it (``auto`` = detect).

Only the Hyprland path is exercised on the author's machine; the others are written to
spec + unit-tested and are considered EXPERIMENTAL until validated on those sessions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from . import osutil

HYPRLAND = "hyprland"
SWAY = "sway"
WAYLAND = "wayland"  # generic Wayland (GNOME/KDE) — degraded (no focus CLI)
X11 = "x11"
WINDOWS = "windows"  # native Win32 (Phase 2) — ctypes focus, PowerShell paste/clipboard
_KNOWN = (HYPRLAND, SWAY, WAYLAND, X11, WINDOWS)


def _run(cmd: list[str], timeout: float = 2.0) -> str | None:
    """Run ``cmd``, return stdout on success else None (never raises)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _desktop_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return ((cfg or {}).get("desktop") or {}) if cfg else {}


def detect_backend() -> str:
    """Pick a backend from the environment. wlroots compositors expose their own
    sockets; fall back to generic Wayland, then X11, then whatever tool exists."""
    if osutil.IS_WINDOWS:
        return WINDOWS
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return HYPRLAND
    if os.environ.get("SWAYSOCK"):
        return SWAY
    if os.environ.get("WAYLAND_DISPLAY"):
        return WAYLAND
    if os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "x11":
        return X11
    if shutil.which("hyprctl"):
        return HYPRLAND
    if shutil.which("swaymsg"):
        return SWAY
    if shutil.which("xdotool"):
        return X11
    return WAYLAND


def backend(cfg: dict[str, Any] | None = None) -> str:
    """Active backend; ``[desktop] backend`` overrides detection (``auto`` = detect)."""
    choice = str(_desktop_cfg(cfg).get("backend", "auto")).strip().lower()
    return choice if choice in _KNOWN else detect_backend()


# --------------------------------------------------------------- focused window

def _hyprland_active() -> dict[str, str] | None:
    out = _run(["hyprctl", "activewindow", "-j"])
    if not out:
        return None
    try:
        win = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(win, dict) or not win.get("class"):
        return None
    return {"class": win.get("class", ""), "title": win.get("title", ""),
            "id": win.get("address", "")}


def _sway_focused(node: dict) -> dict | None:
    if node.get("focused") and node.get("type") in ("con", "floating_con"):
        return node
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        found = _sway_focused(child)
        if found:
            return found
    return None


def _sway_active() -> dict[str, str] | None:
    out = _run(["swaymsg", "-t", "get_tree"])
    if not out:
        return None
    try:
        tree = json.loads(out)
    except json.JSONDecodeError:
        return None
    node = _sway_focused(tree) if isinstance(tree, dict) else None
    if not node:
        return None
    props = node.get("window_properties") or {}
    cls = node.get("app_id") or props.get("class") or ""  # wayland app_id / X11 class
    return {"class": cls, "title": node.get("name") or "", "id": str(node.get("id", ""))}


def _x11_active() -> dict[str, str] | None:
    if not shutil.which("xdotool"):
        return None
    wid = _run(["xdotool", "getactivewindow"])
    if not wid or not wid.strip():
        return None
    wid = wid.strip()
    title = (_run(["xdotool", "getwindowname", wid]) or "").strip()
    cls = ""
    if shutil.which("xprop"):
        # WM_CLASS(STRING) = "instance", "ClassName"  — the class is the last field.
        raw = (_run(["xprop", "-id", wid, "WM_CLASS"]) or "").partition("=")[2]
        parts = [p.strip().strip('"') for p in raw.split(",") if p.strip()]
        cls = parts[-1] if parts else ""
    return {"class": cls, "title": title, "id": wid}


def _windows_active() -> dict[str, str] | None:
    """Focused window on Windows via Win32 (ctypes): GetForegroundWindow → title +
    owning process exe. ``class`` carries the exe basename (e.g. ``WindowsTerminal.exe``),
    mirroring how the Linux backends report a window class. Unvalidated on Linux —
    exercised on a real Windows box."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = wintypes.HWND
    kernel32.OpenProcess.restype = wintypes.HANDLE

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        try:
            size = wintypes.DWORD(260)
            path_buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
                exe = path_buf.value.rsplit("\\", 1)[-1]  # basename
        finally:
            kernel32.CloseHandle(handle)
    return {"class": exe, "title": title, "id": str(int(hwnd))}


def active_window(cfg: dict[str, Any] | None = None) -> dict[str, str] | None:
    """The focused window as ``{class, title, id}``, or None if undeterminable — which
    the focus gate treats as 'don't block'. Generic Wayland (GNOME/KDE) has no reliable
    focused-window CLI, so it returns None (focus gate off; the wake word still works)."""
    match = {HYPRLAND: _hyprland_active, SWAY: _sway_active, X11: _x11_active,
             WINDOWS: _windows_active}
    fn = match.get(backend(cfg))
    return fn() if fn else None


# --------------------------------------------------------------- typing / paste

def _type_tool(cfg: dict[str, Any] | None) -> str | None:
    override = str(_desktop_cfg(cfg).get("type_tool", "")).strip()
    if override:
        return override if shutil.which(override) else None
    order = {
        HYPRLAND: ("wtype", "ydotool"),
        SWAY: ("wtype", "ydotool"),
        WAYLAND: ("ydotool", "wtype"),  # GNOME/KDE reject wtype's protocol
        X11: ("xdotool", "ydotool"),
    }.get(backend(cfg), ())  # unknown/Windows backend → no shell typing tool
    return next((t for t in order if shutil.which(t)), None)


def _powershell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def _windows_paste_and_submit(submit: bool) -> bool:
    """Paste (Ctrl+V) into the focused window via PowerShell SendKeys, then Enter if
    ``submit``. PowerShell avoids hand-rolled ctypes SendInput structs — slower, but a
    Windows tester can run the same one-liner to debug. False if PowerShell is absent."""
    pwsh = _powershell()
    if not pwsh:
        return False
    keys = "^v" + ("{ENTER}" if submit else "")
    cmd = ("Add-Type -AssemblyName System.Windows.Forms; "
           f"[System.Windows.Forms.SendKeys]::SendWait('{keys}')")
    return subprocess.run([pwsh, "-NoProfile", "-Command", cmd]).returncode == 0


def paste_and_submit(cfg: dict[str, Any] | None = None, *, submit: bool = False) -> bool:
    """Inject the Ctrl+Shift+V paste chord into the focused window, then Enter if
    ``submit``. Returns False if no typing tool is available (caller keeps the text on
    the clipboard as the fallback)."""
    if backend(cfg) == WINDOWS:
        return _windows_paste_and_submit(submit=submit)
    tool = _type_tool(cfg)
    if tool == "wtype":
        subprocess.run(
            ["wtype", "-M", "ctrl", "-M", "shift", "-k", "v", "-m", "shift", "-m", "ctrl"],
            check=False,
        )
        if submit:
            subprocess.run(["wtype", "-k", "Return"], check=False)
        return True
    if tool == "xdotool":
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"], check=False)
        if submit:
            subprocess.run(["xdotool", "key", "Return"], check=False)
        return True
    if tool == "ydotool":
        # keycodes: ctrl=29 shift=42 v=47 enter=28; ":1" press, ":0" release.
        subprocess.run(
            ["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"], check=False
        )
        if submit:
            subprocess.run(["ydotool", "key", "28:1", "28:0"], check=False)
        return True
    return False


# --------------------------------------------------------------- clipboard

def _clip_argv(cfg: dict[str, Any] | None) -> list[str] | None:
    """argv that reads text on stdin and sets the clipboard, for the best available
    tool (Wayland ``wl-copy``, X11 ``xclip``/``xsel``)."""
    tools = [
        ("wl-copy", ["wl-copy"]),
        ("xclip", ["xclip", "-selection", "clipboard"]),
        ("xsel", ["xsel", "--clipboard", "--input"]),
    ]
    if backend(cfg) in (X11,):  # prefer X11 tools first on X11
        tools = tools[1:] + tools[:1]
    override = str(_desktop_cfg(cfg).get("clipboard_tool", "")).strip()
    if override:
        tools = [(t, argv) for t, argv in tools if t == override] + tools
    return next((argv for t, argv in tools if shutil.which(t)), None)


def _win_clipboard_set(text: str) -> None:
    """Set the Windows clipboard, Unicode-safe. Prefers PowerShell ``Set-Clipboard``
    (reads all of stdin as one UTF-8 string); falls back to built-in ``clip.exe``."""
    pwsh = _powershell()
    if pwsh:
        cmd = ("[Console]::InputEncoding=[Text.Encoding]::UTF8; "
               "Set-Clipboard -Value ([Console]::In.ReadToEnd())")
        subprocess.run([pwsh, "-NoProfile", "-Command", cmd],
                       input=text, text=True, encoding="utf-8", check=True)
        return
    if shutil.which("clip"):
        subprocess.run(["clip"], input=text, text=True, check=True)
        return
    raise RuntimeError("no clipboard tool — expected PowerShell (Set-Clipboard) or clip.exe")


def clipboard_copy(text: str, cfg: dict[str, Any] | None = None) -> None:
    """Put ``text`` on the clipboard. Raises if no clipboard tool is installed."""
    if backend(cfg) == WINDOWS:
        _win_clipboard_set(text)
        return
    argv = _clip_argv(cfg)
    if argv is None:
        raise RuntimeError(
            "no clipboard tool — install wl-clipboard (Wayland) or xclip/xsel (X11)"
        )
    subprocess.run(argv, input=text, text=True, check=True)


# --------------------------------------------------------------- overlay

def overlay_supported(cfg: dict[str, Any] | None = None) -> bool:
    """The eww pet uses the wlr-layer-shell protocol — only wlroots compositors
    (Hyprland/Sway) provide it. (Whether ``eww`` itself is installed is checked by the
    overlay command.)"""
    return backend(cfg) in (HYPRLAND, SWAY)
