"""Maps Google Chat dialog form inputs to a Freshservice ticket payload.

This is the bare-bones, user-fills-the-form path: the user enters every
field directly in the dialog, so the values arrive already-confirmed. We
build a strict ``TicketCreatePayload`` straight from those inputs, bypassing
the ``TicketDraft`` machinery (which exists for the future flow where Molli
pre-fills fields from a chat summary and the user reviews them).

Pure logic, no I/O — easy to unit test. Validation comes for free: building
``TicketCreatePayload`` raises pydantic ``ValidationError`` on a bad email,
out-of-range enum, empty required field, etc.

Constants injected here (not collected from the user):
    original_more_detail = "Other"   (confirmed valid value in Freshservice)
    source = 4                        (Chat — Molli's universal source)
    type  = "Incident"
    status defaults to 2 (Open) if not supplied.

NOTE: the Molli traceability custom fields (molli_conversation_id,
molli_confidence_score, molli_escalation_reason) are intentionally NOT set
here. They require provisioning in Freshservice first; sending an unknown
custom_fields key returns a 400. Leaving them unset means exclude_none=True
strips them at serialization time.
"""

from __future__ import annotations

from typing import Any

from molli_shared.schemas.ticket import (
    MolliCustomFields,
    TicketCreatePayload,
)

# Injected constants — see module docstring.
_SOURCE_CHAT = 4
_TYPE_INCIDENT = "Incident"


def build_ticket_payload(inputs: dict[str, Any]) -> TicketCreatePayload:
    """Build a validated TicketCreatePayload from extracted dialog inputs.

    Expects ``inputs`` to be the already-parsed form values (see the
    extraction helper in main.py), with these keys:

        email             str   — requester email
        subject           str   — ticket subject
        group             str   — Freshservice group_id, as a string
        affectedLocation  list  — one or more location strings
        systemItem        str   — the System value (-> original_system)
        status            str   — TicketStatus int, as a string
        priority          str   — TicketPriority int, as a string
        description       str   — ticket description

    Selection widgets return their values as strings (and multi-selects as
    lists of strings), so group/status/priority are cast to int here. That's
    the str -> int half of the int -> str -> int round-trip: the form_options
    ids/values were stringified for the widget, and we convert back now.

    Raises:
        pydantic.ValidationError: if any value fails the strict schema
            (bad email, status/priority outside the allowed set, empty
            subject/description, empty location list, etc.).
        ValueError / KeyError: if a required key is missing or a numeric
            field isn't castable to int.
    """
    custom_fields = MolliCustomFields(
        original_system=inputs["systemItem"],
        original_more_detail=inputs["moreDetail"],
        msf_affected_location=inputs["affectedLocation"],
        # Molli traceability fields left unset on purpose — see docstring.
    )

    return TicketCreatePayload(
        email=inputs["email"],
        subject=inputs["subject"],
        description=inputs["description"],
        group_id=int(inputs["group"]),
        custom_fields=custom_fields,
        priority=int(inputs["priority"]),
        source=_SOURCE_CHAT,
        type=_TYPE_INCIDENT,
    )
