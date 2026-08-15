"""Tests for osutil (OS detection) and the OS-aware path resolution in paths.py.

The Windows branches are exercised on Linux by forcing ``osutil.IS_WINDOWS`` and
mocking the environment — so CI proves the Windows wiring without a Windows box.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from voxpane import osutil, paths


def test_platform_constants_match_sys_platform():
    assert osutil.IS_LINUX == sys.platform.startswith("linux")
    assert osutil.IS_WINDOWS == sys.platform.startswith("win")
    assert osutil.IS_MACOS == (sys.platform == "darwin")


def test_detached_kwargs_posix_uses_new_session():
    if osutil.IS_WINDOWS:  # this assertion is for the POSIX default
        return
    assert osutil.detached_kwargs() == {"start_new_session": True}


def test_detached_kwargs_windows_uses_creationflags(monkeypatch):
    monkeypatch.setattr(osutil, "IS_WINDOWS", True)
    kwargs = osutil.detached_kwargs()
    assert "creationflags" in kwargs and "start_new_session" not in kwargs


# ------------------------------------------------------------- paths (POSIX)

def test_runtime_dir_honours_xdg(monkeypatch):
    monkeypatch.setattr(paths.osutil, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert paths.runtime_dir() == paths.Path("/run/user/1000") / "voxpane"


def test_config_dir_honours_xdg(monkeypatch):
    monkeypatch.setattr(paths.osutil, "IS_WINDOWS", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/x/.config")
    assert paths.config_dir() == paths.Path("/home/x/.config") / "voxpane"


# ------------------------------------------------------------- paths (Windows)

def test_windows_dirs_use_appdata_and_localappdata(monkeypatch):
    monkeypatch.setattr(paths.osutil, "IS_WINDOWS", True)
    roaming = r"C:\Users\me\AppData\Roaming"
    local = r"C:\Users\me\AppData\Local"
    monkeypatch.setenv("APPDATA", roaming)
    monkeypatch.setenv("LOCALAPPDATA", local)
    assert paths.config_dir() == paths.Path(roaming) / "voxpane"
    assert paths.data_dir() == paths.Path(local) / "voxpane"
    assert paths.state_dir() == paths.Path(local) / "voxpane" / "state"
    assert paths.runtime_dir() == paths.Path(local) / "voxpane" / "runtime"


def test_macos_dirs_use_library_application_support(monkeypatch):
    monkeypatch.setattr(paths.osutil, "IS_WINDOWS", False)
    monkeypatch.setattr(paths.osutil, "IS_MACOS", True)
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    support = paths.Path.home() / "Library" / "Application Support"
    assert paths.config_dir() == support / "voxpane"
    assert paths.data_dir() == support / "voxpane"
    assert paths.state_dir() == support / "voxpane" / "state"


def test_windows_runtime_dir_never_calls_getuid(monkeypatch):
    # os.getuid() doesn't exist on Windows; the Windows branch must never reach it.
    monkeypatch.setattr(paths.osutil, "IS_WINDOWS", True)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    def boom():
        raise AssertionError("getuid must not be called on Windows")

    monkeypatch.setattr(paths.os, "getuid", boom, raising=False)
    assert paths.runtime_dir().name == "runtime"  # resolves without raising

# (the Windows speak-lock is covered in test_windows_speak.py with a fake msvcrt)


# ------------------------------------------------------------- process helpers

def test_pid_alive_windows_uses_tasklist(monkeypatch):
    monkeypatch.setattr(osutil, "IS_WINDOWS", True)
    monkeypatch.setattr(osutil.subprocess, "run",
                        lambda cmd, **k: SimpleNamespace(stdout=" 4242 Console"))
    assert osutil.pid_alive(4242) is True


def test_terminate_windows_uses_taskkill(monkeypatch):
    monkeypatch.setattr(osutil, "IS_WINDOWS", True)
    seen = {}
    monkeypatch.setattr(osutil.subprocess, "run",
                        lambda cmd, **k: seen.update(cmd=cmd) or SimpleNamespace(returncode=0))
    assert osutil.terminate(4242) is True
    assert seen["cmd"][:2] == ["taskkill", "/F"] and "4242" in seen["cmd"]


def test_terminate_posix_sends_sigterm(monkeypatch):
    if osutil.IS_WINDOWS:
        return
    seen = {}
    monkeypatch.setattr(osutil.os, "kill", lambda pid, sig: seen.update(pid=pid, sig=sig))
    assert osutil.terminate(4242) is True
    assert seen["pid"] == 4242 and seen["sig"] == osutil.signal.SIGTERM
