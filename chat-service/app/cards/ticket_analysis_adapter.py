"""Adapter: converts a TicketAnalysis into make_draft() keyword arguments.

Lives in chat-service (not molli_shared) because it is the only layer that
imports form_options.LOCATIONS / SYSTEM_ITEMS — the shared ticket_analysis
module has no vocabulary dependency and receives lists as plain arguments.

Call analysis_to_draft_fields() to get a dict of FieldConfidence | None values
keyed by the make_draft() parameter names, then unpack it:

    fields = analysis_to_draft_fields(analysis)
    draft = make_draft(email=_fc(user_email, 0.99, "user-stated"), **fields)
"""

from __future__ import annotations

from typing import Any

from molli_shared.schemas.factories import _fc
from molli_shared.schemas.ticket import FieldConfidence
from molli_shared.ticket_analysis import (
    TicketAnalysis,
    snap_list_to_vocabulary,
    snap_to_vocabulary,
)

from app.cards.form_options import LOCATIONS, SYSTEM_ITEMS, more_detail_options

_GROUP_LABEL_TO_ID: dict[str, int | None] = {
    "IT": 5000233136,
    "Ops": 5000233137,
    "HR": None,  # Preiss has no HR group in Freshservice; HR escalations are
    # handled outside the ticketing system, so this stays None.
    "general": None,
}


def analysis_to_draft_fields(
    analysis: TicketAnalysis,
) -> dict[str, FieldConfidence | None]:
    """Return make_draft() keyword args built from a TicketAnalysis.

    Vocabulary-snaps system_raw → SYSTEM_ITEMS and locations_raw → LOCATIONS
    using difflib fuzzy matching. Fields that can't be resolved are returned
    as None so the dialog renders them blank for the user to fill in.
    """
    # Group — HR resolves to None (no Freshservice HR group); dialog leaves
    # the group blank for the user to pick.
    group_id: int | None = _GROUP_LABEL_TO_ID.get(analysis.group_label)

    # System item — snap free text to exact vocabulary string
    snapped_system = snap_to_vocabulary(analysis.system_raw or "", SYSTEM_ITEMS)

    # Locations — snap each free-text name; drop unmatched
    snapped_locations = snap_list_to_vocabulary(analysis.locations_raw, LOCATIONS)

    more_detail_vocab = more_detail_options(snapped_system or "")
    snapped_more_detail = snap_to_vocabulary(analysis.more_detail_raw or "", more_detail_vocab)

    result: dict[str, Any] = {
        "subject": _fc(analysis.subject, 0.85, "inferred"),
        "description": _fc(analysis.description, 0.80, "inferred"),
        "priority": _fc(analysis.priority, 0.60, "inferred"),
        "group_id": _fc(group_id, 0.75, "inferred") if group_id is not None else None,
        "original_system": (_fc(snapped_system, 0.85, "inferred") if snapped_system else None),
        "original_more_detail": (
            _fc(snapped_more_detail, 0.75, "inferred") if snapped_more_detail else None
        ),
        "msf_affected_location": (
            _fc(snapped_locations, 0.70, "inferred") if snapped_locations else None
        ),
        "computer_name_if_it_issue": (
            _fc(analysis.computer_name, 0.90, "user-stated") if analysis.computer_name else None
        ),
    }
    return result
