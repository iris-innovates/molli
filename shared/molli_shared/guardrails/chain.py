"""Guardrail chain runner.

Runs all guardrails in priority order. Any BLOCK or ESCALATE short-circuits
the pipeline — Gemini is never called for those verdicts.

Priority order (from guardrail-eval-prompts.md):
  MENTAL_HEALTH > OSHA_TIER1 > FHA > FCRA > DATA_PRIVACY_BLOCK > ESCALATION > DATA_PRIVACY_REDACT > ALLOW

The runner also handles:
  - Logging every verdict (no raw message content beyond session)
  - REDACT: strips PII from message before passing to Gemini
  - OSHA Tier 2: appends mandatory safety referral suffix to Gemini response
  - Data Privacy Mode B: scans Gemini output before returning to user
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Action, Guardrail, GuardrailVerdict
from .data_priv import DataPrivacyGuardrail, redact_pii
from .escalation import EscalationGuardrail
from .fair_housing import FairHousingGuardrail
from .llm_classifier import FHAFCRAClassifier
from .mental_health import MentalHealthGuardrail
from .osha import OSHAGuardrail
from .hr_legal import HRLegalGuardrail


@dataclass
class ChainResult:
    """What the chain returns to the request handler."""

    verdict: GuardrailVerdict
    should_call_gemini: bool
    message_to_gemini: str | None  # redacted if REDACT action
    append_to_response: str | None  # OSHA Tier 2 referral suffix
    response_to_user: str | None  # canned response when not calling Gemini


# ---------------------------------------------------------------------------
# Chain definition — order determines priority
# ---------------------------------------------------------------------------

_GUARDRAIL_CHAIN: list[Guardrail] = [
    MentalHealthGuardrail(),  # highest priority
    OSHAGuardrail(),  # Tier 1 emergency second
    FairHousingGuardrail(),  # FHA regex — fast path
    FHAFCRAClassifier(),  # LLM semantic fallback for FHA (only reached if regex passes)
    HRLegalGuardrail(),  # HR/Legal risk signals
    DataPrivacyGuardrail(),  # Data Privacy (BLOCK); REDACT handled after
    EscalationGuardrail(),  # Escalation last
]

_DATA_PRIVACY_GUARDRAIL = DataPrivacyGuardrail()


async def run_chain(
    message: str,
    user_email: str,
    space_id: str = "unknown",
    session_id: str = "unknown",
) -> ChainResult:
    """Run all guardrails. Short-circuit on BLOCK or ESCALATE."""

    redacted_message = message
    redact_verdict: GuardrailVerdict | None = None
    append_suffix: str | None = None

    for guardrail in _GUARDRAIL_CHAIN:
        verdict = await guardrail.check(redacted_message, user_email)

        if verdict.action == Action.BLOCK:
            return ChainResult(
                verdict=verdict,
                should_call_gemini=False,
                message_to_gemini=None,
                append_to_response=None,
                response_to_user=verdict.canned_response,
            )

        if verdict.action == Action.ESCALATE:
            return ChainResult(
                verdict=verdict,
                should_call_gemini=False,
                message_to_gemini=None,
                append_to_response=None,
                response_to_user=verdict.canned_response,
            )

        if verdict.action == Action.REDACT:
            # Strip PII, continue chain with redacted message
            redacted_message, _ = redact_pii(redacted_message)
            redact_verdict = verdict  # remember to notify user of redaction

        if (
            verdict.action == Action.ALLOW
            and verdict.category == "OSHA"
            and verdict.canned_response  # OSHA Tier 2 referral suffix
        ):
            append_suffix = verdict.canned_response

    # All guardrails passed — call Gemini with (possibly redacted) message
    final_verdict = redact_verdict or GuardrailVerdict(
        action=Action.ALLOW,
        category="CHAIN",
        reason="All guardrails passed",
    )

    return ChainResult(
        verdict=final_verdict,
        should_call_gemini=True,
        message_to_gemini=redacted_message,
        append_to_response=append_suffix,
        response_to_user=redact_verdict.canned_response if redact_verdict else None,
    )


async def scan_gemini_output(
    response: str,
    user_email: str,
    space_id: str = "unknown",
    session_id: str = "unknown",
) -> tuple[str, GuardrailVerdict]:
    """Mode B — scan Gemini response for PII before returning to user."""
    verdict = await _DATA_PRIVACY_GUARDRAIL.check_output(response)

    if verdict.action == Action.REDACT:
        clean_response, _ = redact_pii(response)
        return clean_response, verdict

    return response, verdict
