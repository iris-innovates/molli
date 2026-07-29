"""Pydantic models for Freshservice ticket operations.

Two related model groups live here:

1. **Strict models** — the shape of data Molli actually sends to and receives
   from Freshservice. ``TicketCreatePayload`` is what the client POSTs.

2. **Draft models** — what Molli builds during a chat conversation, before
   the user has reviewed the modal and confirmed. ``TicketDraft`` wraps each
   field with confidence/source metadata so the modal UI can render
   pre-fills appropriately. The draft is converted to a strict payload at
   submit time via ``TicketDraft.to_payload()``.

Field names match Freshservice's API exactly. Do not rename for stylistic
consistency; the API rejects unknown keys.

When adding new fields to ``MolliCustomFields``, confirm the custom field has
been provisioned in Freshservice first. Sending an unknown ``custom_fields``
key returns a 400 from the API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
# Freshservice exposes these as integers. Using Literal types makes the
# valid set explicit and catches typos at validation time.

# 2=Open, 3=Pending, 4=Resolved, 5=Closed
TicketStatus = Literal[2, 3, 4, 5]

# 1=Low, 2=Medium, 3=High, 4=Urgent
TicketPriority = Literal[1, 2, 3, 4]

# 1=Email, 2=Portal, 3=Phone, 4=Chat, 5=Feedback widget,
# 6=Yammer, 7=AWS Cloudwatch, 8=Pagerduty, 9=Walkup, 10=Slack
# Molli always uses 4 (Chat).
TicketSource = Literal[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

FieldSource = Literal["user-stated", "inferred", "default", "lookup", "user-edited"]

EscalationReason = Literal[
    "no-confident-answer",
    "user-requested-human",
    "guardrail-triggered",
    "other",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DraftIncompleteError(ValueError):
    """Raised when ``TicketDraft.to_payload()`` is called on a draft missing
    one or more required fields. The ``missing_fields`` attribute lists them.
    """

    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = missing_fields
        super().__init__(
            f"Cannot convert draft to payload — missing required fields: "
            f"{', '.join(missing_fields)}"
        )


# ---------------------------------------------------------------------------
# Strict (API-bound) models
# ---------------------------------------------------------------------------


class MolliCustomFields(BaseModel):
    """Custom fields on Preiss's Freshservice ticket schema.

    Required for every ticket Molli creates:
        original_system, original_more_detail, msf_affected_location.

    Conditionally required:
        computer_name_if_it_issue — when original_system is IT-related.
        Chat-service resolves from Workspace Admin SDK when available.

    Molli-specific traceability fields require provisioning in the
    Freshservice admin console before they can be set. Until then they
    remain ``None`` and are stripped at serialization time.
    """

    model_config = ConfigDict(extra="forbid")

    original_system: str
    original_more_detail: str
    msf_affected_location: list[str] = Field(min_length=1)

    computer_name_if_it_issue: str | None = None

    molli_conversation_id: str | None = None
    molli_confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    molli_escalation_reason: EscalationReason | None = None


class TicketCreatePayload(BaseModel):
    """Payload for POST /api/v2/tickets.

    ``description`` accepts plain text or HTML. Freshservice auto-wraps plain
    text in ``<div>`` tags during storage; both forms are retrievable via GET
    as ``description`` (HTML) and ``description_text`` (stripped). Prefer
    plain text for short summaries, HTML for chat transcripts and structured
    content like the hardware-request scenario.

    Use ``.model_dump(exclude_none=True)`` when serializing to JSON for the
    API. Sending ``null`` for optional fields can cause 400s on some fields.
    """

    model_config = ConfigDict(extra="forbid")

    # Required by Freshservice
    email: EmailStr
    subject: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)

    # Required by Preiss's Freshservice configuration
    group_id: int
    custom_fields: MolliCustomFields

    # Optional with sensible defaults for chat-originated tickets
    status: TicketStatus = 2
    priority: TicketPriority = 2
    source: TicketSource = 4
    type: str = "Incident"
    tags: list[str] = Field(default_factory=list)


class RequesterRecord(BaseModel):
    """Subset of a Freshservice requester record relevant to Molli.

    Freshservice returns dozens of fields; we model only what the chat service
    consumes. ``extra="ignore"`` keeps the model lightweight as the API
    evolves.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    primary_email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    active: bool = True


class CreatedTicket(BaseModel):
    """Subset of the ticket object returned from a successful POST.

    Freshservice wraps the response in a ``{"ticket": {...}}`` envelope at
    the transport layer; the client unwraps before validating against this
    model.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    subject: str
    status: int
    priority: int
    group_id: int | None = None
    requester_id: int | None = None
    created_at: str


# ---------------------------------------------------------------------------
# Draft (pre-submit) models
# ---------------------------------------------------------------------------


class FieldConfidence(BaseModel):
    """Per-field metadata for the draft modal UI.

    The chat-service builds these as it extracts values from the conversation:
    ``confidence`` drives how prominently the modal flags the field for user
    review (low confidence -> highlight, ask user to verify; high confidence
    -> pre-fill quietly). ``source`` records where the value came from so the
    UI can show it ("Auto-detected from your laptop name" vs "From your
    profile") and so we can analyze Molli's prediction quality over time.
    """

    model_config = ConfigDict(extra="forbid")

    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    source: FieldSource


class TicketDraft(BaseModel):
    """Molli's in-progress proposed ticket, before user confirmation.

    Persisted in Firestore under collection ``ticket_drafts`` keyed by
    ``draft_id``. Every field is optional because the chat-service builds the
    draft incrementally as the conversation progresses. The user reviews the
    modal, optionally edits fields, then submits — at which point
    ``to_payload()`` produces a strict ``TicketCreatePayload`` for the API.

    Fields whose ``FieldConfidence.value`` is ``None`` mean "Molli has no
    proposal — the modal should show this as empty and require the user to
    fill it in" (if required) or "leave it as default" (if optional).
    """

    model_config = ConfigDict(extra="forbid")

    # Identity
    draft_id: str
    conversation_id: str
    created_at: datetime
    updated_at: datetime

    # Molli always sets these — never user-editable
    molli_conversation_id: str
    molli_confidence_score: float = Field(ge=0.0, le=1.0)
    molli_escalation_reason: EscalationReason

    # Fields the user can review and edit in the modal
    email: FieldConfidence | None = None
    subject: FieldConfidence | None = None
    description: FieldConfidence | None = None
    group_id: FieldConfidence | None = None
    priority: FieldConfidence | None = None

    # Custom fields (also user-editable in the modal)
    original_system: FieldConfidence | None = None
    original_more_detail: FieldConfidence | None = None
    msf_affected_location: FieldConfidence | None = None
    computer_name_if_it_issue: FieldConfidence | None = None

    # Optional metadata
    tags: list[str] = Field(default_factory=list)

    def to_payload(
        self,
        overrides: dict[str, Any] | None = None,
    ) -> TicketCreatePayload:
        """Convert this draft to a strict ``TicketCreatePayload``.

        Apply ``overrides`` on top of the draft's values — used by the
        chat-service when the user has edited fields in the modal. Override
        keys correspond to plain field names (``email``, ``original_system``,
        etc.), not the wrapped ``FieldConfidence`` shape.

        Raises:
            DraftIncompleteError: if any required field is missing both in
                the draft and in overrides.
        """
        overrides = overrides or {}

        def resolved(name: str) -> Any:
            """Pull a value from overrides if present, otherwise from the
            draft's FieldConfidence wrapper if present, otherwise None."""
            if name in overrides:
                return overrides[name]
            wrapped = getattr(self, name, None)
            if wrapped is None:
                return None
            return wrapped.value

        required_top_level = ["email", "subject", "description", "group_id"]
        required_custom = [
            "original_system",
            "original_more_detail",
            "msf_affected_location",
        ]

        missing: list[str] = []
        for name in required_top_level + required_custom:
            if resolved(name) is None:
                missing.append(name)
        if missing:
            raise DraftIncompleteError(missing)

        custom = MolliCustomFields(
            original_system=resolved("original_system"),
            original_more_detail=resolved("original_more_detail"),
            msf_affected_location=resolved("msf_affected_location"),
            computer_name_if_it_issue=resolved("computer_name_if_it_issue"),
            molli_conversation_id=self.molli_conversation_id,
            molli_confidence_score=self.molli_confidence_score,
            molli_escalation_reason=self.molli_escalation_reason,
        )

        # Priority — let user override, default to Medium if unset
        priority_value = resolved("priority")
        if priority_value is None:
            priority_value = 2

        return TicketCreatePayload(
            email=resolved("email"),
            subject=resolved("subject"),
            description=resolved("description"),
            group_id=resolved("group_id"),
            custom_fields=custom,
            priority=priority_value,
            tags=list(self.tags),
        )
