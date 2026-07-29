"""Unit tests for the deterministic intro/capabilities short-circuit."""

from __future__ import annotations

import pytest
from app.intro import MOLLI_INTRO_MESSAGE, is_intro_query

WHITELIST_VARIANTS = [
    "hi",
    "Hello",
    "HEY",
    " help ",
    "/help",
    "Who are you?",
    "what are you",
    "WHAT CAN MOLLI DO",
    "what do you do",
    "who is molli",
    "what is molli?",
    "how can you help",
    "what can you help with",
    "how do you work",
    "what can i ask you",
]


@pytest.mark.parametrize("text", WHITELIST_VARIANTS)
def test_whitelist_phrases_match(text: str) -> None:
    assert is_intro_query(text) is True


REAL_QUESTIONS = [
    "who do I contact for help with the printer",
    "help me refund a payment in Entrata",
    "what is the wifi password",
    "how do I reset my password",
    "who do I contact for help resetting my password",
]


@pytest.mark.parametrize("text", REAL_QUESTIONS)
def test_real_questions_do_not_match(text: str) -> None:
    assert is_intro_query(text) is False


def test_empty_and_whitespace_do_not_match() -> None:
    assert is_intro_query("") is False
    assert is_intro_query("   ") is False


def test_intro_message_mentions_molli_and_preiss_without_the_preiss_company() -> None:
    assert "Molli" in MOLLI_INTRO_MESSAGE
    assert "Preiss" in MOLLI_INTRO_MESSAGE
    assert "The Preiss Company" not in MOLLI_INTRO_MESSAGE
