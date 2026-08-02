"""Command-dictionary post-processing — milestone M4.

Skeleton test names mapped to the plan's acceptance criteria: cover every
dictionary category, plus a mid-sentence match that must NOT fire. Un-skip as
postprocess.apply() is implemented.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="postprocess is milestone M4 — not built yet")


def test_text_replacement_slash_command_at_start():
    ...


def test_slash_command_mid_sentence_stays_literal():
    # "the slash clear command is useful" must NOT become "/clear".
    ...


def test_key_action_scratch_that():
    ...


def test_transform_camel_case():
    ...


def test_transform_snake_kebab_pascal():
    ...


def test_fixups_git_commit():
    ...


def test_filler_stripping():
    ...


def test_trailing_submit_phrase_sets_flag_and_is_removed():
    ...
