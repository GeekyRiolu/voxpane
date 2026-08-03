"""Tests for `voxpane install-bindings` (M2). All I/O against a temp hypr dir."""

from __future__ import annotations

import pytest

from voxpane import bindings


def test_installs_into_existing_conf(tmp_path):
    conf = tmp_path / "bindings.conf"
    conf.write_text("# existing binds\nbindd = SUPER, T, Term, exec, alacritty\n")

    result = bindings.install(tmp_path)

    assert result.status == "installed" and result.kind == "conf" and result.path == conf
    assert result.backup and result.backup.exists()
    text = conf.read_text()
    assert "V, Toggle voxpane listening on/off, exec, voxpane listen --toggle" in text
    assert "alacritty" in text  # original content preserved


def test_is_idempotent(tmp_path):
    (tmp_path / "bindings.conf").write_text("")

    first = bindings.install(tmp_path)
    second = bindings.install(tmp_path)

    assert first.status in ("installed", "created")
    assert second.status == "already"
    assert (tmp_path / "bindings.conf").read_text().count("voxpane listen --toggle") == 1


def test_prefers_lua_and_writes_o_bind(tmp_path):
    (tmp_path / "bindings.lua").write_text("-- binds\n")
    (tmp_path / "bindings.conf").write_text("")  # both exist; lua wins

    result = bindings.install(tmp_path)

    assert result.kind == "lua"
    lua_text = (tmp_path / "bindings.lua").read_text()
    assert 'o.bind("SUPER ALT", "V", "exec, voxpane listen --toggle"' in lua_text
    assert "voxpane" not in (tmp_path / "bindings.conf").read_text()  # conf untouched


def test_creates_conf_when_none_exists(tmp_path):
    result = bindings.install(tmp_path)

    assert result.status == "created" and result.kind == "conf"
    assert (tmp_path / "bindings.conf").exists()
    assert result.sourced is False


def test_detects_when_sourced(tmp_path):
    (tmp_path / "hyprland.conf").write_text("source = ~/.config/hypr/bindings.conf\n")
    result = bindings.install(tmp_path)
    assert result.sourced is True


def test_missing_hypr_dir_raises(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        bindings.install(tmp_path / "nope")
