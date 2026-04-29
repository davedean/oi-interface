"""Tests for clean_transcript in server/stt.py"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from stt import clean_transcript


def test_leading_um():
    assert clean_transcript("um, can you help me") == "can you help me."


def test_leading_uhh():
    assert clean_transcript("uhh what is this") == "what is this."


def test_like_preserved():
    # "like" is a content word, not a filler
    assert clean_transcript("I like this option") == "I like this option."


def test_so_preserved():
    # "so" is not a filler in this context
    assert clean_transcript("so what about the code") == "so what about the code."


def test_whitespace_collapse():
    assert clean_transcript("  hello   world  ") == "hello world."


def test_existing_punctuation():
    assert clean_transcript("already punctuated.") == "already punctuated."


def test_exclamation():
    assert clean_transcript("hello, world!") == "hello, world!"


def test_empty():
    assert clean_transcript("") == ""


def test_leading_umm_hmm():
    assert clean_transcript("umm hmm let me think") == "let me think."


def test_no_double_period():
    assert clean_transcript("it ends with a period.") == "it ends with a period."


def test_question_mark():
    assert clean_transcript("what is this?") == "what is this?"


def test_multiple_leading_fillers():
    # All leading fillers are stripped: "um uh hello" → "hello."
    assert clean_transcript("um uh hello") == "hello."


def test_preserves_code_content():
    # Technical terms should never be stripped
    assert clean_transcript("run pip install faster-whisper") == "run pip install faster-whisper."