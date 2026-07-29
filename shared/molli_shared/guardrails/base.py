"""Guardrail layer.

Categories:
- Mental health: detect distress, escalate to EAP, never give clinical advice
- Fair Housing (FHA): refuse questions about tenant screening on protected classes
- FCRA: no background check / credit guidance without HR authorization
- HR / Legal: harassment, discrimination, retaliation disclosures
- OSHA / Safety: urgent safety -> immediate escalation
- Escalation: 3-tier (answer -> ticket -> human handoff)
- Data Privacy: DLP-scan inputs, no PII in chat logs

Each guardrail is a callable that inspects an inbound message and returns a
GuardrailVerdict. The chain runs all of them; any block stops the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Action(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"  # refuse, return canned response
    ESCALATE = "escalate"  # answer + immediate human handoff
    REDACT = "redact"  # allow but strip flagged content first


@dataclass(frozen=True)
class GuardrailVerdict:
    action: Action
    category: str
    reason: str
    canned_response: str | None = None


class Guardrail(Protocol):
    name: str

    async def check(self, message: str, user_email: str) -> GuardrailVerdict: ...


# Concrete guardrails live in sibling modules (mental_health.py, fair_housing.py,
# fcra.py, hr_legal.py, osha.py, data_priv.py, escalation.py). The runnable
# chain and its priority order live in chain.py.

GUARDRAIL_CHAIN: list[Guardrail] = []
