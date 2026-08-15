"""Stop in-progress TTS playback — `voxpane hush` and the voice "stop" word.

Kills the ``pw-play`` the speaker started (its pid is recorded in
``paths.play_pid_file()``) and clears the speaking marker, so the Dot goes quiet
mid-sentence when you've heard enough.
"""

from __future__ import annotations

import os
import signal
import subprocess

from . import osutil, paths


def hush() -> bool:
    """Kill the current TTS playback. Returns True if something was stopped."""
    try:
        pid: int | None = int(paths.play_pid_file().read_text().strip())
    except (OSError, ValueError):
        pid = None

    stopped = False
    if pid is not None:
        if osutil.IS_WINDOWS:
            # os.kill semantics differ on Windows; taskkill the player process.
            result = subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            stopped = result.returncode == 0
        else:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped = True
            except ProcessLookupError:
                pass

    for marker in (paths.play_pid_file(), paths.speaking_marker()):
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
    return stopped
