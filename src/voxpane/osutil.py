"""Tiny OS-detection + process helpers.

The rest of the code branches on these constants instead of scattering
``sys.platform`` string checks. voxpane is Linux-first (Phase 1 shipped
multi-desktop Linux); Windows support is being added incrementally (Phase 2), and
this is the seam the OS-specific paths hang off — filesystem locations, audio
capture, process spawning — kept in one place so a future macOS phase slots in the
same way.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def detached_kwargs() -> dict[str, Any]:
    """``Popen`` kwargs that detach a child so it outlives the launching process.

    POSIX starts a new session (``setsid``); Windows does not honour
    ``start_new_session`` and instead wants a detached process in its own group.
    """
    if IS_WINDOWS:
        flags = 0
        for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
            flags |= getattr(subprocess, name, 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


def pid_alive(pid: int) -> bool:
    """Whether a process is running. IMPORTANT: never TERMINATES it — ``os.kill(pid,
    0)`` *kills* the target on Windows, so there we probe with ``tasklist`` instead."""
    if IS_WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True)
        return f" {pid} " in out.stdout or f"\t{pid}\t" in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate(pid: int) -> bool:
    """Stop a process — SIGTERM on POSIX, ``taskkill /F`` on Windows. Returns True if
    the signal/kill was issued (False if the process was already gone)."""
    if IS_WINDOWS:
        return subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                              capture_output=True).returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
