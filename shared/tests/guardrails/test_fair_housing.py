"""Tests for the FairHousingGuardrail.

Covers:
- FHA trigger patterns (protected classes, tenant decision language)
- Screening/credit/adverse-action language is intentionally excluded here and
  handled by FCRAGuardrail instead — see test_fcra.py
- Exclusion patterns (Grace Hill, job screening interviews)
- Normal messages that should pass through
"""

from __future__ import annotations

import pytest

from molli_shared.guardrails.fair_housing import FairHousingGuardrail
from molli_shared.guardrails.base import Action

USER = "test.user@preiss.com"

guardrail = FairHousingGuardrail()


# ---------------------------------------------------------------------------
# FHA triggers — should BLOCK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocks_fair_housing_direct():
    verdict = await guardrail.check("can you explain the fair housing rules?", USER)
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_fha_abbreviation():
    verdict = await guardrail.check("what does FHA require us to do?", USER)
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_deny_applicant():
    verdict = await guardrail.check("can we deny an applicant based on income?", USER)
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_canned_response_is_set():
    verdict = await guardrail.check("can we reject an applicant based on race?", USER)
    assert verdict.canned_response is not None
    assert "HR" in verdict.canned_response


# ---------------------------------------------------------------------------
# Protected class standalone triggers — should BLOCK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocks_race_standalone():
    verdict = await guardrail.check("can we reject an applicant based on race?", USER)
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_religion_standalone():
    verdict = await guardrail.check("is it okay to ask about someone's religion?", USER)
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_national_origin():
    verdict = await guardrail.check(
        "do we have to accept tenants regardless of national origin?", USER
    )
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_familial_status():
    verdict = await guardrail.check(
        "can we limit occupancy based on familial status?", USER
    )
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_disability():
    verdict = await guardrail.check(
        "what do we do if an applicant has a disability?", USER
    )
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_sex():
    verdict = await guardrail.check("can we ask applicants about their sex?", USER)
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_sexual_orientation():
    verdict = await guardrail.check(
        "does sexual orientation affect the application process?", USER
    )
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_gender_identity():
    verdict = await guardrail.check(
        "should we note gender identity on the lease?", USER
    )
    assert verdict.action == Action.BLOCK


@pytest.mark.asyncio
async def test_blocks_source_of_income():
    verdict = await guardrail.check("can we reject based on source of income?", USER)
    assert verdict.action == Action.BLOCK


# ---------------------------------------------------------------------------
# Exclusion patterns — should ALLOW
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allows_grace_hill():
    verdict = await guardrail.check("how do I access Grace Hill training?", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_screening_criteria():
    # Screening/adverse-action language is FCRA territory, not FHA — see test_fcra.py.
    verdict = await guardrail.check(
        "what are the screening criteria for applicants?", USER
    )
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_adverse_action_letter():
    verdict = await guardrail.check("how do I write an adverse action letter?", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_screening_interview():
    verdict = await guardrail.check(
        "I have a screening call with a vendor tomorrow", USER
    )
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_screening_meeting():
    verdict = await guardrail.check(
        "can you help me prep for my screening interview?", USER
    )
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_sexual_harassment():
    verdict = await guardrail.check(
        "what is our policy on sexual harassment complaints?", USER
    )
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_religious_holiday():
    verdict = await guardrail.check(
        "can an employee take time off for a religious holiday?", USER
    )
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_disability_insurance():
    verdict = await guardrail.check("how do I file a disability insurance claim?", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_race_condition():
    verdict = await guardrail.check(
        "we have a race condition in the Entrata sync script", USER
    )
    assert verdict.action == Action.ALLOW


# ---------------------------------------------------------------------------
# Normal messages — should ALLOW
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allows_password_reset():
    verdict = await guardrail.check("how do I reset my Google password?", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_pto_question():
    verdict = await guardrail.check("how many PTO days do I have left?", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_printer_question():
    verdict = await guardrail.check("how do I connect to the office printer?", USER)
    assert verdict.action == Action.ALLOW


@pytest.mark.asyncio
async def test_allows_entrata_question():
    verdict = await guardrail.check("how do I request access to Entrata?", USER)
    assert verdict.action == Action.ALLOW
