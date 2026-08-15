"""Tiny OS-detection + process helpers.

The rest of the code branches on these constants instead of scattering
``sys.platform`` string checks. voxpane is Linux-first (Phase 1 shipped
multi-desktop Linux); Windows support is being added incrementally (Phase 2), and
this is the seam the OS-specific paths hang off — filesystem locations, audio
capture, process spawning — kept in one place so a future macOS phase slots in the
same way.
"""

from __future__ import annotations

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
