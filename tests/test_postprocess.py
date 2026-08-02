"""Command-dictionary post-processing — milestone M4.

Covers every dictionary category plus a mid-sentence slash match that must NOT
fire, per the plan's acceptance criteria.
"""

from __future__ import annotations

from voxpane import config, postprocess


def _apply(text, **behavior):
    cfg = config.defaults()
    cfg["behavior"].update(behavior)
    return postprocess.apply(text, config.default_commands(), cfg)


# --- [text]: slash commands (start-anchored) ---

def test_slash_command_at_start():
    assert _apply("slash clear").text == "/clear"


def test_slash_command_mid_sentence_stays_literal():
    out = _apply("the slash clear command is useful").text
    assert "/clear" not in out
    assert "slash clear" in out


# --- [text]: symbols anywhere ---

def test_symbol_replacements_anywhere():
    assert _apply("foo open paren bar close paren").text == "foo ( bar )"


def test_new_line_token():
    assert "\n" in _apply("first new line second").text


# --- [keys] ---

def test_key_actions():
    assert _apply("scratch that").text == "C-u"
    assert _apply("escape escape").text == "Escape Escape"


# --- [transforms] ---

def test_transform_camel():
    assert _apply("camel case user profile").text == "userProfile"


def test_transform_snake_kebab_pascal():
    assert _apply("snake case my var name").text == "my_var_name"
    assert _apply("kebab case my var name").text == "my-var-name"
    assert _apply("pascal case user profile").text == "UserProfile"


# --- [fixups] ---

def test_fixups():
    assert _apply("get commit").text == "git commit"
    assert _apply("pseudo make install").text == "sudo make install"
    assert _apply("i love no JS").text == "i love Node.js"


# --- filler stripping ---

def test_filler_stripping():
    assert _apply("um please uh refactor this", strip_filler=True).text == "please refactor this"


def test_fillers_kept_when_disabled():
    assert "um" in _apply("um please refactor", strip_filler=False).text


# --- trailing submit phrase ---

def test_trailing_submit_phrase_sets_flag_and_is_removed():
    result = _apply("refactor the parser send it")
    assert result.submit is True
    assert result.text == "refactor the parser"


def test_no_submit_when_absent():
    assert _apply("refactor the parser").submit is False


def test_submit_phrase_mid_sentence_does_not_fire():
    result = _apply("send it to the printer")
    assert result.submit is False
    assert "send it" in result.text
