"""Tests for the config loader and defaults parity."""

from __future__ import annotations

from voxpane import config

_TOP_LEVEL = {"audio", "whisper", "delivery", "behavior", "speak", "summary"}


def test_defaults_have_expected_sections():
    cfg = config.defaults()
    assert _TOP_LEVEL.issubset(cfg)


def test_safety_defaults_cover_same_sections():
    # The hardcoded fallback must not drift from the shipped TOML.
    assert _TOP_LEVEL.issubset(config._SAFETY_DEFAULTS)


def test_shipped_toml_matches_safety_default_sections():
    path = config._default_toml_path()
    assert path is not None, "config/config.default.toml should be locatable"
    from_toml = set(config.defaults())
    from_safety = set(config._SAFETY_DEFAULTS)
    assert from_toml == from_safety


def test_user_config_deep_merges_over_defaults(tmp_path):
    user = tmp_path / "config.toml"
    user.write_text('[delivery]\nauto_submit = true\n')
    cfg = config.load(user)
    # Overridden key wins...
    assert cfg["delivery"]["auto_submit"] is True
    # ...while sibling keys and other sections survive.
    assert cfg["delivery"]["mode"] == "tmux"
    assert cfg["whisper"]["language"] == "en"


def test_missing_user_config_returns_defaults(tmp_path):
    cfg = config.load(tmp_path / "does-not-exist.toml")
    assert cfg == config.defaults()


def test_model_path_expands_home():
    cfg = config.defaults()
    assert not str(config.model_path(cfg)).startswith("~")
