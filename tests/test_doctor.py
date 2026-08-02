"""Tests for `voxpane doctor` (M0)."""

from __future__ import annotations

import copy

from voxpane import config, doctor


def _cfg():
    return copy.deepcopy(config.defaults())


def test_run_checks_returns_checks():
    checks = doctor.run_checks(_cfg())
    assert checks
    assert all(isinstance(c, doctor.Check) for c in checks)


def test_missing_model_fails_with_hint(tmp_path):
    cfg = _cfg()
    cfg["whisper"]["model"] = str(tmp_path / "nope.bin")
    model_check = next(c for c in doctor.run_checks(cfg) if c.name == "whisper model")
    assert not model_check.ok
    assert model_check.hint


def test_render_marks_pass_and_fail():
    ok = doctor.Check("thing", True, "found")
    bad = doctor.Check("other", False, "missing", "install it")
    rendered = doctor.render([ok, bad])
    assert "✓" in rendered and "✗" in rendered
    assert "install it" in rendered


def test_main_returns_int():
    out = []
    rc = doctor.main(_cfg(), printer=out.append)
    assert isinstance(rc, int)
    assert any("voxpane doctor" in line for line in out)
