"""HR / Legal Risk guardrail.

Detects harassment, discrimination, retaliation, and hostile work environment
disclosures. Per the High-Risk Conversation Governance Framework (2026):

  - Route to Sally Sousa (HR) ONLY
  - Never alert or involve the employee's direct manager
  - Do not investigate or interpret the disclosure
  - Auto-create a Freshservice ticket (Phase 1 — not yet wired)
  - Provide anonymous tip option in canned response

Action: ESCALATE — return confidential intake canned response.
"""

from __future__ import annotations

import re

from .base import Action, GuardrailVerdict

# ---------------------------------------------------------------------------
# Trigger patterns — HR/Legal risk signals
# ---------------------------------------------------------------------------

_HARASSMENT_PATTERNS: list[str] = [
    r"\bsexual harassment\b",
    r"\bharassing (me|us|staff|employees)\b",
    r"\bbeing harassed\b",
    r"\bunwanted (advances|touching|contact|comments)\b",
    r"\b(made|making) me (feel )?uncomfortable\b",
    r"\btouched me (inappropriately|without permission)\b",
    r"\bsaid something (inappropriate|offensive|sexual)\b",
    r"\bcreating a hostile (work )?(environment|workplace)\b",
    r"\bhostile work environment\b",
    r"\bworkplace harassment\b",
]

_DISCRIMINATION_PATTERNS: list[str] = [
    r"\bbeing discriminated against\b",
    r"\bdiscrimination (complaint|claim|issue)\b",
    r"\btreated differently because of (my |their )?(race|gender|age|religion|disability|pregnancy|nationality)\b",
    r"\bunfair(ly)? (treated|passed over|denied).{0,40}(because|due to|based on)\b",
    r"\bpassed over for (promotion|raise|opportunity).{0,40}(because|due to)\b",
    r"\bage discrimination\b",
    r"\bgender discrimination\b",
    r"\bracial discrimination\b",
    r"\bpassed over for (a |the )?(promotion|raise|opportunity)\b",
    r"\bage (discrimination|related)\b",
    r"\bbecause of my age\b",
]

_RETALIATION_PATTERNS: list[str] = [
    r"\bretaliat(ion|ing|ed)\b",
    r"\bpunished for (reporting|complaining|saying)\b",
    r"\bfired (for|because) (reporting|complaining)\b",
    r"\bthreatened (me )?(for|after|because) (reporting|complaining|filing)\b",
    r"\bafraid to report\b",
    r"\bscared to say (anything|something)\b",
    r"\bdon'?t want to get in trouble for (reporting|saying|telling)\b",
]

_HOSTILE_WORKPLACE_PATTERNS: list[str] = [
    r"\bhostile (workplace|work environment|environment)\b",
    r"\bintimidating (work )?environment\b",
    r"\bfeel (unsafe|threatened|uncomfortable).{0,20}(at work|workplace)\b",
    r"\bmanager (is|was) (yelling|screaming|threatening|abusive)\b",
    r"\bverbally (abused|attacked|threatened) (at work|by my manager|by a coworker)\b",
    r"\bphysically (threatened|intimidated) at work\b",
    r"\bworkplace (violence|threat|intimidation)\b",
    r"\bmanager has been (yelling|screaming|threatening|abusive)\b",
    r"\b(yelling|screaming|threatening).{0,30}in front of\b",
    r"\bverbally (abusing|threatening) (me|staff|employees)\b",
]

_INVESTIGATION_PATTERNS: list[str] = [
    r"\bwant to file (a )?(complaint|report|claim)\b",
    r"\bhow do i report (harassment|discrimination|retaliation)\b",
    r"\bwho do i (talk to|report to|contact) about (harassment|discrimination|retaliation)\b",
    r"\bneed to report (something|an incident|a situation) (confidentially|privately|anonymously)\b",
    r"\bwant to file (a )?(harassment|discrimination|retaliation)?\s*complaint\b",
    r"\bfile a complaint\b",
]

# Exclusion patterns — general questions that should not trigger
_EXCLUSION_PATTERNS: list[str] = [
    r"\bharassment (policy|training|module|course|definition|complaint process)\b",
    r"\bdiscrimination (policy|training|module|course|definition)\b",
    r"\bretaliation (policy|definition|training|module|course|clause|complaint process)\b",
    r"\bwhat is (sexual harassment|workplace discrimination|retaliation)\b",
    r"\bwhat'?s (the |our |preiss'?s? )?(retaliation|hostile work environment|harassment|discrimination) policy\b",
    r"\bdefine (harassment|discrimination|retaliation)\b",
    r"\bhostile work environment (definition|training|policy|module|course|example|scenario|for (a |the )?training)\b",
    r"\bwithout (it |this )?(looking|appearing|seeming) like (retaliation|harassment|discrimination)\b",
    r"\bworkplace violence (policy|prevention|training|protocol|procedure|program|resources)\b",
    r"\b(violence|threat|intimidation) prevention (policy|program|training|protocol)\b",
]

CANNED_RESPONSE = """Thank you for trusting Molli with this. What you've shared sounds serious and deserves proper attention.

I'm routing this to HR confidentially right now. Sally Sousa in HR will follow up with you directly — this will not be shared with your direct manager.

A few important things:
- You have the right to report without fear of retaliation
- You can also report anonymously through the anonymous tip option — ask Sally for details
- HR is the only team that will see this conversation

Someone from HR will reach out within 2 hours. If you feel unsafe right now, please contact your site manager or call 911.

You did the right thing by speaking up. 💙"""


def _matches_any(text: str, patterns: list[str]) -> str | None:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return p
    return None


class HRLegalGuardrail:
    name = "hr_legal"

    async def check(self, message: str, user_email: str) -> GuardrailVerdict:
        lower = message.lower()

        # Exclusion check first
        if _matches_any(lower, _EXCLUSION_PATTERNS):
            return GuardrailVerdict(
                action=Action.ALLOW,
                category="HR_LEGAL",
                reason="Matched exclusion pattern (policy/training question)",
            )

        signal_type: str | None = None
        matched: str | None = None

        if m := _matches_any(lower, _HARASSMENT_PATTERNS):
            signal_type, matched = "harassment", m
        elif m := _matches_any(lower, _DISCRIMINATION_PATTERNS):
            signal_type, matched = "discrimination", m
        elif m := _matches_any(lower, _RETALIATION_PATTERNS):
            signal_type, matched = "retaliation", m
        elif m := _matches_any(lower, _HOSTILE_WORKPLACE_PATTERNS):
            signal_type, matched = "hostile_workplace", m
        elif m := _matches_any(lower, _INVESTIGATION_PATTERNS):
            signal_type, matched = "wants_to_report", m

        if signal_type:
            return GuardrailVerdict(
                action=Action.ESCALATE,
                category="HR_LEGAL",
                reason=f"HR/Legal risk detected: type={signal_type} | pattern={matched} | route_to_sally=true | do_not_alert_manager=true",
                canned_response=CANNED_RESPONSE,
            )

        return GuardrailVerdict(
            action=Action.ALLOW,
            category="HR_LEGAL",
            reason="No HR/Legal risk signals detected",
        )
