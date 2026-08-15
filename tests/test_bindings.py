"""Tests for `voxpane install-bindings` (M2). All I/O against a temp config dir."""

from __future__ import annotations

import pytest

from voxpane import bindings


def test_installs_into_existing_conf(tmp_path):
    conf = tmp_path / "bindings.conf"
    conf.write_text("# existing binds\nbindd = SUPER, T, Term, exec, alacritty\n")

    result = bindings.install_hyprland(tmp_path)

    assert result.status == "installed" and result.kind == "conf" and result.path == conf
    assert result.backup and result.backup.exists()
    text = conf.read_text()
    assert "V, Toggle voxpane listening on/off, exec, voxpane listen --toggle" in text
    assert "alacritty" in text  # original content preserved


def test_is_idempotent(tmp_path):
    (tmp_path / "bindings.conf").write_text("")

    first = bindings.install_hyprland(tmp_path)
    second = bindings.install_hyprland(tmp_path)

    assert first.status in ("installed", "created")
    assert second.status == "already"
    assert (tmp_path / "bindings.conf").read_text().count("voxpane listen --toggle") == 1


def test_prefers_lua_and_writes_o_bind(tmp_path):
    (tmp_path / "bindings.lua").write_text("-- binds\n")
    (tmp_path / "bindings.conf").write_text("")  # both exist; lua wins

    result = bindings.install_hyprland(tmp_path)

    assert result.kind == "lua"
    lua_text = (tmp_path / "bindings.lua").read_text()
    assert 'o.bind("SUPER ALT", "V", "exec, voxpane listen --toggle"' in lua_text
    assert "voxpane" not in (tmp_path / "bindings.conf").read_text()  # conf untouched


def test_creates_conf_when_none_exists(tmp_path):
    result = bindings.install_hyprland(tmp_path)

    assert result.status == "created" and result.kind == "conf"
    assert (tmp_path / "bindings.conf").exists()
    assert result.sourced is False


def test_detects_when_sourced(tmp_path):
    (tmp_path / "hyprland.conf").write_text("source = ~/.config/hypr/bindings.conf\n")
    result = bindings.install_hyprland(tmp_path)
    assert result.sourced is True


def test_missing_hypr_dir_raises(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        bindings.install_hyprland(tmp_path / "nope")


# ------------------------------------------------------------------- sway

def test_sway_writes_bindsym_into_config_d(tmp_path):
    (tmp_path / "config").write_text("include config.d/*\n")

    result = bindings.install_sway(tmp_path)

    assert result.status == "created" and result.kind == "sway"
    target = tmp_path / "config.d" / "voxpane.conf"
    assert result.path == target and target.is_file()
    text = target.read_text()
    assert "bindsym Mod4+Mod1+v exec voxpane listen --toggle" in text
    assert "bindsym Mod4+Mod1+s exec voxpane hush" in text
    assert result.sourced is True  # main config includes config.d


def test_sway_is_idempotent(tmp_path):
    (tmp_path / "config").write_text("")
    first = bindings.install_sway(tmp_path)
    second = bindings.install_sway(tmp_path)
    assert first.status == "created" and second.status == "already"
    target = tmp_path / "config.d" / "voxpane.conf"
    assert target.read_text().count("voxpane listen --toggle") == 1


def test_sway_warns_when_config_d_not_included(tmp_path):
    (tmp_path / "config").write_text("# no include here\n")
    result = bindings.install_sway(tmp_path)
    assert result.sourced is False


# ------------------------------------------------------------------- dispatch

def test_install_dispatches_on_backend(monkeypatch, tmp_path):
    from voxpane import desktop

    monkeypatch.setattr(bindings, "install_sway", lambda base=None: bindings.Result(
        "created", tmp_path, "sway"))
    monkeypatch.setattr(desktop, "backend", lambda cfg=None: desktop.SWAY)
    assert bindings.install().kind == "sway"


def test_install_manual_on_unsupported_backend(monkeypatch):
    from voxpane import desktop

    monkeypatch.setattr(desktop, "backend", lambda cfg=None: desktop.X11)
    result = bindings.install()
    assert result.kind == "manual" and result.status == "manual"
    assert any("voxpane listen --toggle" in line for line in result.instructions)
    assert any("Super+Alt+V" in line for line in result.instructions)
