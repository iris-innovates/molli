"""Deterministic HR-contact reply for "how do I contact HR" style messages.

Short-circuits before the guardrail chain and RAG pipeline, same rationale as
app/intro.py: a static string that echoes no user input and calls no model,
so there's nothing to guard against and no reason to pay for an LLM round trip.
"""

from __future__ import annotations

HR_CONTACT_MESSAGE = (
    "hr@tpco.com, If it's urgent, please reach out directly to your manager "
    "or the relevant department lead."
)

# Full phrases that unambiguously ask for HR's contact info, not HR content
# questions ("what is the HR policy on PTO" must NOT match -- that's a real
# question for RAG). Matched as complete, normalized strings, same as
# app/intro.py's _PHRASES, to keep the false-positive rate low.
_PHRASES = {
    "how do i contact hr",
    "how can i contact hr",
    "how do i reach hr",
    "how can i reach hr",
    "how do i get in touch with hr",
    "how can i get in touch with hr",
    "how do i reach out to hr",
    "how can i reach out to hr",
    "how do i email hr",
    "how do i contact human resources",
    "how can i contact human resources",
    "how do i reach human resources",
    "how can i reach human resources",
    "who do i contact for hr",
    "who do i contact in hr",
    "who do i contact at hr",
    "contact hr",
    "hr contact",
    "hr contact info",
    "hr contact information",
    "hr email",
    "hr's email",
    "what is hr's email",
    "what is hr email",
    "what is the hr email",
    "hr phone number",
    "hr number",
}

_STRIP_CHARS = " \t\r\n.,!?'\""


def is_hr_contact_query(text: str) -> bool:
    """True if `text` is asking how to contact/reach HR.

    Deliberately narrow: HR content questions ("what is the HR policy on
    PTO", "how do I submit an HR ticket") must not match -- only phrases
    that unambiguously ask for HR's contact info do.
    """
    normalized = text.strip().strip(_STRIP_CHARS).lower().strip()
    if not normalized:
        return False

    return normalized in _PHRASES
