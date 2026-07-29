"""Test/dev factory for building ``TicketDraft`` objects.

Lets the dialog pre-fill flow (open dialog -> widgets carry ``value`` from the
draft -> user edits inline -> submit) be built and tested end-to-end against a
realistic draft, independent of whatever produces a real draft from Molli's
confidence/fallback path.

Design notes:
- Every editable field is wrapped in ``FieldConfidence`` exactly as a real
  draft would be, so the pre-fill code reads ``.value`` uniformly.
- ``make_draft`` defaults to a complete, high-confidence IT-scenario draft.
- Helpers cover the cases the dialog has to survive: a field Molli couldn't
  propose (``value=None`` -> widget shows empty), and a fully empty draft
  (only the never-user-editable Molli fields set).
- ``original_more_detail`` is set to "Other" here so a factory draft round-trips
  cleanly through ``to_payload()``. Pass ``include_more_detail=False`` to drop
  it from the draft instead, for testing a caller that injects it as an
  override.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from molli_shared.schemas.ticket import (
    FieldConfidence,
    FieldSource,
    TicketDraft,
)


def _fc(
    value: Any, confidence: float = 0.9, source: FieldSource = "inferred"
) -> FieldConfidence:
    """Wrap a value in FieldConfidence with sensible test defaults."""
    return FieldConfidence(value=value, confidence=confidence, source=source)


def make_draft(
    *,
    draft_id: str = "draft-test-0001",
    conversation_id: str = "conv-test-0001",
    include_more_detail: bool = True,
    **field_overrides: FieldConfidence | None,
) -> TicketDraft:
    """Return a complete, high-confidence ``TicketDraft`` for an IT scenario.

    Pass any editable field name as a keyword to override its FieldConfidence
    (or set it to ``None`` to simulate "Molli had no proposal"):

        make_draft(subject=None)                       # subject comes through empty
        make_draft(priority=_fc(4, source="user-stated"))

    ``include_more_detail=False`` drops ``original_more_detail`` from the draft,
    for testing the path where the Confirm handler injects it as an override.
    """
    now = datetime.now(timezone.utc)

    # Defaults — a realistic "can't log in" IT escalation Molli couldn't resolve.
    defaults: dict[str, FieldConfidence | None] = {
        "email": _fc("lindsey.bowman@preiss.com", 0.99, "user-stated"),
        "subject": _fc("Can't log into Google account", 0.85, "inferred"),
        "description": _fc(
            "User reports being locked out of their Google account after "
            "multiple failed login attempts. Self-service recovery did not "
            "resolve. Escalated by Molli.",
            0.80,
            "inferred",
        ),
        "group_id": _fc(5000233136, 0.75, "inferred"),  # int; "IT" group
        "priority": _fc(2, 0.60, "default"),  # int; Medium
        "original_system": _fc(
            "Google Apps (Gmail/email / Drive / Calendar / Docs)", 0.90, "inferred"
        ),
        "msf_affected_location": _fc(["Raleigh Condos"], 0.70, "inferred"),
        "computer_name_if_it_issue": _fc("LAPTOP-LB-014", 0.65, "lookup"),
    }
    if include_more_detail:
        defaults["original_more_detail"] = _fc("Other", 1.0, "default")

    # Apply caller overrides (including explicit None to clear a field).
    for name, fc in field_overrides.items():
        defaults[name] = fc

    return TicketDraft(
        draft_id=draft_id,
        conversation_id=conversation_id,
        created_at=now,
        updated_at=now,
        # Never user-editable — Molli always sets these.
        molli_conversation_id=conversation_id,
        molli_confidence_score=0.42,
        molli_escalation_reason="no-confident-answer",
        **defaults,
    )


def make_partial_draft() -> TicketDraft:
    """A draft where Molli couldn't propose subject or location.

    Exercises the dialog's empty-field handling: these widgets should render
    with no pre-filled ``value`` and the user fills them in (required-widget
    enforcement on submit still applies).
    """
    return make_draft(subject=None, msf_affected_location=None)


def make_empty_draft() -> TicketDraft:
    """A draft with no editable proposals at all — only the Molli-set fields.

    Equivalent to "fallback fired but Molli extracted nothing useful from the
    conversation." Every editable widget renders empty. Useful for confirming
    the dialog degrades to the same blank form as the manual dialogtest path.
    """
    return make_draft(
        email=None,
        subject=None,
        description=None,
        group_id=None,
        priority=None,
        original_system=None,
        msf_affected_location=None,
        computer_name_if_it_issue=None,
        include_more_detail=False,
    )
