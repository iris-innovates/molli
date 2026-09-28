"""Unit tests for the deterministic HR-contact short-circuit."""

from __future__ import annotations

import pytest
from app.hr_contact import HR_CONTACT_MESSAGE, is_hr_contact_query

WHITELIST_VARIANTS = [
    "How do I contact HR?",
    "how can i contact hr",
    "How do I reach HR",
    "how can i reach hr",
    "How do I get in touch with HR?",
    "how do i reach out to hr",
    "How do I email HR",
    "how do i contact human resources",
    "Who do I contact for HR?",
    "who do i contact in hr",
    "Contact HR",
    "HR contact",
    "hr contact info",
    "HR email",
    "what is hr's email?",
    "HR phone number",
    "hr number",
]


@pytest.mark.parametrize("text", WHITELIST_VARIANTS)
def test_whitelist_phrases_match(text: str) -> None:
    assert is_hr_contact_query(text) is True


REAL_QUESTIONS = [
    "what is the hr policy on pto",
    "how do i submit an hr ticket for benefits",
    "how much pto do i accrue",
    "who do i contact for help with the printer",
    "what is the wifi password",
]


@pytest.mark.parametrize("text", REAL_QUESTIONS)
def test_real_questions_do_not_match(text: str) -> None:
    assert is_hr_contact_query(text) is False


def test_empty_and_whitespace_do_not_match() -> None:
    assert is_hr_contact_query("") is False
    assert is_hr_contact_query("   ") is False


def test_hr_contact_message_is_exact() -> None:
    assert HR_CONTACT_MESSAGE == (
        "hr@tpco.com, If it's urgent, please reach out directly to your manager "
        "or the relevant department lead."
    )
