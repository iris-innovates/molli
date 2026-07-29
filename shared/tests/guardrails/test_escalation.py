"""Tests for EscalationGuardrail — Tier 3 human handoff detection.

Covers:
- Explicit HR-request phrasing (→ ESCALATE, category ESCALATION_HR)
- General human-request / frustration / repeat-question signals
  (→ ALLOW, category ESCALATION — passed through to the RAG/ticket flow
  rather than blocked outright)
- Graceful decline (never mind)
- Normal messages that must NOT trigger escalation
"""

from __future__ import annotations

import pytest

from molli_shared.guardrails.base import Action
from molli_shared.guardrails.escalation import EscalationGuardrail

USER = "test.user@preiss.com"

guardrail = EscalationGuardrail()


# ---------------------------------------------------------------------------
# Tier 3 — explicit HR requests → ESCALATE (category ESCALATION_HR)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contact_hr_directly():
    verdict = await guardrail.check("I'd like to contact HR directly", USER)
    assert verdict.action == Action.ESCALATE
    assert verdict.category == "ESCALATION_HR"


@pytest.mark.asyncio
async def test_transfer_me_to_hr():
    verdict = await guardrail.check("please transfer me to the HR team", USER)
    assert verdict.action == Action.ESCALATE
    assert verdict.category == "ESCALATION_HR"


@pytest.mark.asyncio
async def test_dont_feel_comfortable_in_ticket():
    verdict = await guardrail.check(
        "I don't feel comfortable putting this in a ticket", USER
    )
    assert verdict.action == Action.ESCALATE
    assert verdict.category == "ESCALATION_HR"


@pytest.mark.asyncio
async def test_something_sensitive_at_work():
    verdict = await guardrail.check(
        "I need to talk about something sensitive that happened at work", USER
    )
    assert verdict.action == Action.ESCALATE
    assert verdict.category == "ESCALATION_HR"


# ---------------------------------------------------------------------------
# Tier 3 — general human requests → ALLOW, category ESCALATION
# (passed through to the RAG/ticket flow rather than blocked outright)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_talk_to_a_person():
    verdict = await guardrail.check("I need to talk to a person", USER)
    assert verdict.action == Action.ALLOW
    assert verdict.category == "ESCALATION"


@pytest.mark.asyncio
async def test_speak_with_a_human():
    verdict = await guardrail.check("can I speak with a human", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_get_a_human():
    verdict = await guardrail.check("just get me a human", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_get_a_real_person():
    verdict = await guardrail.check("can you get me a real person please", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_want_a_human():
    verdict = await guardrail.check("I want a human", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_would_like_to_speak_with_someone():
    verdict = await guardrail.check("I'd like to speak with someone", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_want_to_talk_to_someone():
    verdict = await guardrail.check("I want to talk to someone", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_escalate_this():
    verdict = await guardrail.check("can you escalate this", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_escalate_my_issue():
    verdict = await guardrail.check("please escalate my issue", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_connect_me_with():
    verdict = await guardrail.check("can you connect me with someone in HR", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_transfer_me_to_a_person():
    verdict = await guardrail.check("can you transfer me to a person", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_already_asked_twice():
    verdict = await guardrail.check(
        "I already asked this twice and molli didn't help", USER
    )
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_molli_didnt_answer():
    verdict = await guardrail.check("Molli hasn't answered my question", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_who_do_i_call():
    verdict = await guardrail.check("who do I actually call about this", USER)
    assert verdict.action == Action.ALLOW


# ---------------------------------------------------------------------------
# Tier 2 — low-confidence follow-up → ALLOW, category ESCALATION
# (passed through to RAG for another attempt)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_that_didnt_answer():
    verdict = await guardrail.check("that didn't answer my question", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_not_what_i_asked():
    verdict = await guardrail.check("that's not what I asked", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_still_confused():
    verdict = await guardrail.check("I still don't understand", USER)
    assert verdict.action == Action.ALLOW


# ---------------------------------------------------------------------------
# Graceful decline → ALLOW
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_never_mind():
    verdict = await guardrail.check("never mind, thanks anyway", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_ill_figure_it_out():
    verdict = await guardrail.check("I'll figure it out myself", USER)
    assert verdict.action == Action.ALLOW


# ---------------------------------------------------------------------------
# Normal messages — must NOT trigger escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allows_normal_hr_question():
    verdict = await guardrail.check("how do I update my direct deposit", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_pto_question():
    verdict = await guardrail.check("how many PTO days do I have left", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_policy_question():
    verdict = await guardrail.check("what is the retaliation policy", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_contact_info_lookup():
    verdict = await guardrail.check(
        "what is Sally de Sousa's contact information", USER
    )
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_person_in_non_escalation_context():
    # "person" appearing in a normal sentence should not trigger
    verdict = await guardrail.check(
        "is there a person who handles benefits questions", USER
    )
    assert verdict.action == Action.ALLOW
