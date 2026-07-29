"""Escalation guardrail — 3-tier escalation flow.

Tier 1: Molli answers from D360 → ALLOW
Tier 2: Low confidence / unknown → offer Freshservice ticket
Tier 3: Sensitive / unresolvable / explicit human request → ESCALATE

This guardrail is the last in the chain. It handles:
- Explicit requests for a human
- Repeat question detection (same question asked 3+ times)
- Frustration signals
"""

from __future__ import annotations

import re
from collections import defaultdict

from .base import Action, GuardrailVerdict

# ---------------------------------------------------------------------------
# Tier 3 — HR-specific escalation
# ---------------------------------------------------------------------------

_HR_REQUEST_PATTERNS: list[str] = [
    r"\b(talk|speak|connect|get) (to|with) (someone in |the )?(hr|human resources)\b",
    r"\b(contact|reach|email|call) (hr|human resources)\b",
    r"\btransfer (me|this).{0,30}(hr|human resources)\b",
    r"\b(i need|want) (to (talk|speak) to )?(hr|human resources)\b",
    r"\bsomething (sensitive|personal|private) (that happened|at work)\b",
    r"\bdon'?t feel comfortable putting (it|this) in a ticket\b",
]

# ---------------------------------------------------------------------------
# Tier 3 — general human handoff (Freshservice ticket, no email)
# ---------------------------------------------------------------------------

_TIER3_PATTERNS: list[str] = [
    r"\b(talk|speak|connect) (to|with) (a )?(real )?(person|human|someone)\b",
    r"\bget (me )?(a )?(real )?(human|person|agent)\b",
    r"\b(want|'?d like) (a |to (talk|speak) (to|with) )?(real )?(person|human|someone|agent)\b",
    r"\btransfer (me|this).{0,30}(person|human|agent|it|manager|team)\b",
    r"\bescalate (this|my (issue|question|request))\b",
    r"\bcontact (it|a manager|my manager|someone) directly\b",
    r"\bwho (do i|can i) (actually )?(call|contact|talk to|reach)\b",
    r"\bi need (this handled|someone to actually|a person)\b",
    r"\bcan you connect me with\b",
    r"\bi already asked (this|twice|before|multiple times)\b",
    r"\b(molli )?(didn'?t|hasn'?t) (help(ed)?|answer(ed)?|fix(ed)?)\b",
    r"\bneed someone to actually fix\b",
    r"\burgent(ly)?.{0,30}(who|call|contact|person)\b",
    r"\bfigure it out myself\b",
]

# Tier 2 — low confidence follow-up (called programmatically, not via pattern)
# These patterns signal the user rejected or wasn't satisfied with an answer
_TIER2_FOLLOWUP_PATTERNS: list[str] = [
    r"\bthat didn'?t (answer|help|work)\b",
    r"\bnot what i (asked|meant|needed)\b",
    r"\bstill (don'?t understand|confused|need help)\b",
    r"\bcan you (try again|be more specific|elaborate)\b",
]

CANNED_RESPONSE_TIER2 = """I wasn't able to find a confident answer to that in Preiss Central. I can open a support ticket so the right team can follow up with you directly.

Here's what I'd include:
  Subject: [auto-generated from question]
  Description: [conversation summary]
  Priority: Normal

[Confirm] [Edit details] [No thanks]"""

CANNED_RESPONSE_TIER3 = """This one needs a human. I'm connecting you with the right person at Preiss and sending them the full context of our conversation so you don't have to repeat yourself.

Someone will follow up with you shortly. If it's urgent, please reach out directly to your manager or the relevant department lead."""

CANNED_RESPONSE_GRACEFUL_CLOSE = (
    """No problem at all — I'm here if you need anything else."""
)

# ---------------------------------------------------------------------------
# Repeat question tracker (in-memory; not persisted across restarts)
# ---------------------------------------------------------------------------

_question_log: dict[str, list[str]] = defaultdict(list)
_REPEAT_THRESHOLD = 3  # same question 3+ times → Tier 3


def _normalize(text: str) -> str:
    """Rough normalization for repeat detection."""
    return re.sub(r"[^a-z0-9 ]", "", text.lower().strip())


def record_question(user_email: str, message: str) -> int:
    """Record a question and return how many times it's been asked."""
    key = _normalize(message)
    log = _question_log[user_email]
    log.append(key)
    return log.count(key)


def _is_hr_request(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in _HR_REQUEST_PATTERNS)


def _is_tier3(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in _TIER3_PATTERNS)


def _is_tier2_followup(text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in _TIER2_FOLLOWUP_PATTERNS)


def _is_graceful_decline(text: str) -> bool:
    return bool(
        re.search(r"\bnever mind\b|\bi'?ll figure it out\b", text, re.IGNORECASE)
    )


class EscalationGuardrail:
    name = "escalation"

    async def check(self, message: str, user_email: str) -> GuardrailVerdict:
        # Graceful close — user declining escalation
        if _is_graceful_decline(message):
            return GuardrailVerdict(
                action=Action.ALLOW,
                category="ESCALATION",
                reason="User declining escalation — close gracefully",
                canned_response=CANNED_RESPONSE_GRACEFUL_CLOSE,
            )

        # Tier 3 — explicit HR request
        if _is_hr_request(message):
            repeat_count = record_question(user_email, message)
            return GuardrailVerdict(
                action=Action.ESCALATE,
                category="ESCALATION_HR",
                reason=f"Tier 3 HR escalation: explicit_hr_request=true | repeat_count={repeat_count}",
                canned_response=CANNED_RESPONSE_TIER3,
            )

        # Tier 3 — general human request (let RAG pipeline show ticket button)
        if _is_tier3(message):
            record_question(user_email, message)
            return GuardrailVerdict(
                action=Action.ALLOW,
                category="ESCALATION",
                reason="Tier 3 escalation: explicit_human_request=true — passing to ticket flow",
            )

        # Tier 2 — low confidence follow-up (pass to RAG for another attempt)
        if _is_tier2_followup(message):
            return GuardrailVerdict(
                action=Action.ALLOW,
                category="ESCALATION",
                reason="Tier 2: low-confidence follow-up detected — passing to RAG",
            )

        # Repeat question check
        repeat_count = record_question(user_email, message)
        if repeat_count >= _REPEAT_THRESHOLD:
            return GuardrailVerdict(
                action=Action.ALLOW,
                category="ESCALATION",
                reason=f"Tier 3: repeat_question_count={repeat_count} >= threshold={_REPEAT_THRESHOLD} — passing to ticket flow",
            )

        return GuardrailVerdict(
            action=Action.ALLOW,
            category="ESCALATION",
            reason="No escalation trigger detected",
        )
