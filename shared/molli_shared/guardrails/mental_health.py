"""Mental Health guardrail.

Detects explicit distress, implicit distress, and crisis terminology.
Uses keyword matching as first pass; delegates ambiguous cases to a
Gemini classification call (stubbed here — wire in Phase 2 tuning).

Action: ESCALATE — return EAP canned response, do not answer any other
part of the message. EAP contact block is loaded from config so it can
be updated without a redeploy (pending Sally Sousa confirmation).
"""

from __future__ import annotations

import re
from functools import lru_cache

from molli_shared.config import get_secret, get_settings

from .base import Action, GuardrailVerdict

# ---------------------------------------------------------------------------
# Trigger pattern sets — from guardrails-design.md §1
# ---------------------------------------------------------------------------

_EXPLICIT_PATTERNS: list[str] = [
    r"\bwant to hurt myself\b",
    r"\bcan'?t go on\b",
    r"\bthinking about suicide\b",
    r"\bdon'?t see the point anymore\b",
    r"\bwant to die\b",
    r"\bthoughts? of (hurting|harming) (myself|themselves)\b",
    r"\bharm myself\b",
    r"\bend my life\b",
    r"\bending it\b",
    r"\bthinking about ending\b",
    # Substance use — coping signals
    r"\b(drinking|using alcohol).{0,40}(to cope|to deal|to get through|to numb|to forget|help[s]? me (sleep|calm|cope))\b",
    r"\busing (drugs?|pills?|weed|marijuana|substances?).{0,30}(to cope|to deal|to get through|more lately|more than i should)\b",
    r"\bcan'?t stop (drinking|using|taking (pills?|drugs?))\b",
    r"\baddicted to (alcohol|pills?|drugs?|drinking|opioids?|painkillers?)\b",
    r"\bi'?ve (relapsed?|been (drinking|using) again)\b",
]

_IMPLICIT_PATTERNS: list[str] = [
    r"\bi'?m not okay\b",
    r"\beverything feels hopeless\b",
    r"\bcan'?t do this anymore\b",
    r"\bno one would notice if i (was|were) gone\b",
    r"\bwant to disappear\b",
    r"\bfeel completely hopeless\b",
    r"\bhaven'?t been okay\b",
    r"\bdon'?t know who to talk to\b",
    r"\bno one.*notice.*gone\b",
    r"\bstruggling with (anxiety|depression|my mental health)\b",
    r"\bnot (been )?okay for a long time\b",
    r"\bi'?m not doing (ok|okay)\b(?!\s+(with|on|in|at)\b)",
    r"\bi'?m not doing well\b(?!\s+(with|on|in|at)\b)",
    r"\bi'?m not doing great\b(?!\s+(with|on|in|at)\b)",
    r"\bhate myself\b",
    r"\bi hate myself\b",
    r"\bfeeling (really )?(low|awful|terrible|horrible|worthless)\b",
    r"\bdon'?t want to (exist|come in|do this anymore)\b",
    r"\bdon'?t want to be here\b(?!\s+(for|during|while|when|at|in|to|until|on)\b)",
    r"\bi can'?t (take|handle|deal with) (this|it) anymore\b",
    r"\bwhat'?s the point (anymore|of (it all|going on|trying|living|being alive|existing|continuing))\b",
    r"\bno reason to (keep going|go on|try)\b",
    # Substance use — concerning patterns without explicit coping admission
    r"\bdrinking (every (day|night)|a lot more|to (sleep|relax)|more than i should)\b",
    r"\brelapsed?\b",
    r"\bmy (drinking|drug use|substance use|alcohol) (has|is).{0,20}(problem|getting worse|out of control)\b",
]

_CRISIS_TERMS: list[str] = [
    r"\boverdos(e|es|ed|ing)\b",
    r"\bself[- ]?harm\b",
    r"\bend it all\b",
    r"\bsuicide\b",
    r"\bsuicidal\b",
    r"\bkill myself\b",
    r"\bhurt myself\b",
    r"\bwant to hurt (myself|someone)\b",
    r"\bthinking about (hurting|harming)\b",
    r"\bsubstance (abuse|use disorder|dependency)\b",
]

# Figurative / benign patterns that must NOT trigger (exclusion list)
_EXCLUSION_PATTERNS: list[str] = [
    r"\bkill this bug\b",
    r"\bkill the (process|server|task|thread|job)\b",
    r"\bdead(line)\b",
    r"\bkilling it\b",  # positive idiom
    r"\bfeeling (really )?low energy\b",  # physical tiredness, not distress
    r"\b(alcohol|drug|substance).{0,20}(policy|test|testing|screening|free workplace|program)\b",
    r"\bdrug.{0,20}(test|testing|screen|check)\b",  # HR admin questions about drug testing
]


@lru_cache(maxsize=1)
def _canned_response() -> str:
    """Build the EAP canned response, loading the contact block from Secret Manager on first call."""
    try:
        eap = get_secret("eap-contact-block", get_settings().gcp_project_id)
    except Exception:
        eap = "(EAP contact details — see HR for current information)"
    return (
        "I'm really glad you reached out, and I want to make sure you get the right support.\n\n"
        "Please connect with Preiss's Employee Assistance Program (EAP) — they offer free, confidential support 24/7:\n\n"
        f"EAP Contact: {eap}\n\n"
        "If you're in immediate danger, please call or text 988 (Suicide & Crisis Lifeline) or go to your nearest emergency room.\n\n"
        "If you'd like to talk to someone at Preiss, you can reach out to Sally Sousa in HR directly.\n\n"
        "You don't have to navigate this alone. 💙"
    )


def _matches_any(text: str, patterns: list[str]) -> str | None:
    """Return the first matching pattern string, or None."""
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return p
    return None


class MentalHealthGuardrail:
    name = "mental_health"

    async def check(self, message: str, user_email: str) -> GuardrailVerdict:
        lower = message.lower()

        # Exclusion check first — bail out fast for known-safe figurative language
        if _matches_any(lower, _EXCLUSION_PATTERNS):
            return GuardrailVerdict(
                action=Action.ALLOW,
                category="MENTAL_HEALTH",
                reason="Matched exclusion pattern (figurative language)",
            )

        signal_type: str | None = None

        if matched := _matches_any(lower, _EXPLICIT_PATTERNS):
            signal_type = "explicit"
        elif matched := _matches_any(lower, _CRISIS_TERMS):
            signal_type = "crisis_term"
        elif matched := _matches_any(lower, _IMPLICIT_PATTERNS):
            signal_type = "implicit"

        if signal_type:
            return GuardrailVerdict(
                action=Action.ESCALATE,
                category="MENTAL_HEALTH",
                reason=f"Mental health signal detected: {signal_type} | pattern: {matched}",
                canned_response=_canned_response(),
            )

        return GuardrailVerdict(
            action=Action.ALLOW,
            category="MENTAL_HEALTH",
            reason="No mental health signals detected",
        )
