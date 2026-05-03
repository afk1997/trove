"""Tests for transcript_io.join_word_text — the single helper that owns
how two transcript word tokens compose into display text. Covers the
specific cases called out in the bug report (helloworld, hello + ',',
$ + 100) plus the punctuation/contraction tables.
"""
from __future__ import annotations

import pytest

from transcript_io import join_word_text, _join_word_tokens, render_segment_text


# ----- the three cases from the bug report -----------------------------

def test_two_words_get_a_space():
    assert join_word_text("hello", "world") == "hello world"


def test_closing_comma_hugs_left():
    assert join_word_text("hello", ",") == "hello,"


def test_dollar_hugs_right():
    assert join_word_text("$", "100") == "$100"


# ----- closing punctuation table ---------------------------------------

@pytest.mark.parametrize("punct", [".", ",", "!", "?", ":", ";", "%", ")", "]", "}", "…", "”", "’", "»"])
def test_closing_punct_hugs_previous_word(punct):
    assert join_word_text("hello", punct) == "hello" + punct


# ----- opening punctuation table ---------------------------------------

@pytest.mark.parametrize("punct", ["(", "[", "{", "$", "#", "@", "“", "‘", "«"])
def test_opening_punct_hugs_following_word(punct):
    assert join_word_text(punct, "world") == punct + "world"


# ----- contractions ----------------------------------------------------

@pytest.mark.parametrize("clitic", ["'s", "n't", "'re", "'ll", "'ve", "'d", "'m"])
def test_contractions_hug_previous_word(clitic):
    # whisper sometimes emits "don" + "'t" or "it" + "'s" as separate tokens
    assert join_word_text("don", clitic) == "don" + clitic


# ----- empty operands --------------------------------------------------

def test_empty_left_returns_right():
    assert join_word_text("", "world") == "world"


def test_empty_right_returns_left():
    assert join_word_text("hello", "") == "hello"


def test_both_empty_returns_empty():
    assert join_word_text("", "") == ""


# ----- the iterable reducer --------------------------------------------

def test_join_word_tokens_full_sentence():
    assert _join_word_tokens(
        ["hello", "world", ",", "this", "costs", "$", "100", "."]
    ) == "hello world, this costs $100."


def test_join_word_tokens_skips_empty():
    assert _join_word_tokens(["hello", "", "world"]) == "hello world"


def test_join_word_tokens_empty_input():
    assert _join_word_tokens([]) == ""


# ----- render_segment_text uses the helper -----------------------------

def test_render_segment_text_handles_punctuation_tokens():
    seg = {"word_idxs": [0, 1, 2, 3]}
    words = [
        {"w": "hello", "deleted": False},
        {"w": ",",     "deleted": False},
        {"w": "world", "deleted": False},
        {"w": "!",     "deleted": False},
    ]
    assert render_segment_text(seg, words) == "hello, world!"


def test_render_segment_text_handles_currency_tokens():
    seg = {"word_idxs": [0, 1, 2, 3, 4]}
    words = [
        {"w": "it",  "deleted": False},
        {"w": "is",  "deleted": False},
        {"w": "$",   "deleted": False},
        {"w": "100", "deleted": False},
        {"w": ".",   "deleted": False},
    ]
    assert render_segment_text(seg, words) == "it is $100."


# ----- reducer invariant: accumulator tail must NOT pose as opener ------

def test_join_word_tokens_us_dollar_does_not_glue_to_next():
    # The accumulator ends with "$" (as the tail of "US$"), but the
    # previous *token* is "US$" not "$" — so the opener rule must NOT
    # fire and we should still get a normal space before "100".
    assert _join_word_tokens(["US$", "100"]) == "US$ 100"


def test_join_word_tokens_word_ending_in_paren_still_spaces():
    # Same idea on the closer side: accumulator ends with "(" because
    # the prev token is "abc(", not "(" — must still space before "x".
    assert _join_word_tokens(["abc(", "x"]) == "abc( x"


def test_render_segment_text_skips_deleted_words_cleanly():
    # Deleting a middle word must NOT leave a double space behind.
    seg = {"word_idxs": [0, 1, 2]}
    words = [
        {"w": "hello", "deleted": False},
        {"w": "cruel", "deleted": True},
        {"w": "world", "deleted": False},
    ]
    assert render_segment_text(seg, words) == "hello world"
