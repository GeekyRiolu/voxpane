"""Desktop notifications via ``notify-send``.

Used two ways:
  * inbound UX — a persistent "🎙 Recording…" toast that is replaced in place by
    "⏳ Transcribing…" and then a transcript preview (via ``replace_id``);
  * the final speaker fallback — when every audible backend fails, the summary
    still surfaces here. This function must therefore never raise.
"""

from __future__ import annotations

import shutil
import subprocess

from . import osutil

# A stable id lets recording/transcribing/preview toasts replace one another
# instead of stacking up.
RECORDING_ID = 42_100


def _notify_windows(summary: str, body: str, expire_ms: int | None) -> None:
    """Fire-and-forget Windows notification via a WinForms balloon tip (built in —
    no extra dependency). Cannot replace an earlier toast, so replace_id is ignored."""
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        return
    timeout = int(expire_ms) if expire_ms else 4000
    title = summary.replace("'", "''")
    text = (body or summary).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;"
        "$n.Visible=$true;"
        f"$n.ShowBalloonTip({timeout},'{title}','{text}',"
        "[System.Windows.Forms.ToolTipIcon]::Info);"
        f"Start-Sleep -Milliseconds {timeout};$n.Dispose()"
    )
    try:
        subprocess.Popen(
            [pwsh, "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **osutil.detached_kwargs(),
        )
    except OSError:
        return


def notify(
    summary: str,
    body: str = "",
    *,
    replace_id: int | None = None,
    urgency: str = "normal",
    icon: str | None = None,
    expire_ms: int | None = None,
    app_name: str = "voxpane",
) -> int | None:
    """Show a notification. Returns its id (for chaining) or ``None`` on failure.

    Swallows every error: a broken notifier must not take down a voice turn.
    """
    if osutil.IS_WINDOWS:
        _notify_windows(summary, body, expire_ms)
        return replace_id
    if not shutil.which("notify-send"):
        return None

    cmd = ["notify-send", "--app-name", app_name, "--urgency", urgency, "--print-id"]
    if replace_id is not None:
        cmd += ["--replace-id", str(replace_id)]
    if icon:
        cmd += ["--icon", icon]
    if expire_ms is not None:
        cmd += ["--expire-time", str(expire_ms)]
    cmd += [summary, body]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None

    try:
        return int(result.stdout.strip())
    except ValueError:
        return replace_id
