# app/cards/structured_requests.py
"""
Field specs for structured admin-action requests that Molli collects and
routes into a clean Freshservice ticket. These do NOT change the dialog or
TicketCreatePayload shape — collected fields are formatted into the
Description body (see format_description), and group_id + subject are set
on the payload via the existing override path.

Audit basis:
  - Entrata access/permissions: Ops cluster 2, 116 tickets (needs_approval=Y)
  - Distribution list add/remove: IT cluster 2, 71 tickets (needs_approval=Y)
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RequestField:
    key: str  # internal key for the collected-values dict
    label: str  # human label shown in the Description body
    required: bool = True


@dataclass(frozen=True)
class RequestSpec:
    request_type: str  # stable id, used for routing/triggers
    title: str  # header line in the Description body
    group_id: int  # Freshservice group id
    subject_template: str  # str.format() against collected values
    fields: tuple[RequestField, ...]

    def subject(self, values: dict[str, str]) -> str:
        # Fall back to "—" for any missing key so the template never crashes
        safe = {f.key: (values.get(f.key) or "—") for f in self.fields}
        return self.subject_template.format(**safe)


_OPS_GROUP_ID = 5000338615
_IT_GROUP_ID = 5000233136


ENTRATA_ACCESS = RequestSpec(
    request_type="entrata_access",
    title="Entrata access request",
    group_id=_OPS_GROUP_ID,
    subject_template="Entrata access: {access_for} @ {property}",
    fields=(
        RequestField("requester", "Requester"),
        RequestField("access_for", "Access for", required=False),  # may differ from requester
        RequestField("property", "Property"),
        RequestField("permissions", "Permissions requested"),
    ),
)

DISTRIBUTION_LIST = RequestSpec(
    request_type="distribution_list",
    title="Distribution list change",
    group_id=_IT_GROUP_ID,
    subject_template="Distribution list {action}: {target_user} → {list_address}",
    fields=(
        RequestField("requester", "Requester"),
        RequestField("action", "Action (add/remove)"),
        RequestField("target_user", "User to add/remove"),
        RequestField("list_address", "Distribution list"),
    ),
)

SPECS = {s.request_type: s for s in (ENTRATA_ACCESS, DISTRIBUTION_LIST)}

# app/cards/structured_requests.py  (append to the file from step 1)


def _resolve_values(spec: RequestSpec, values: dict[str, str]) -> dict[str, str]:
    """
    Normalize collected values before formatting:
      - strip whitespace on everything
      - for entrata_access, default `access_for` to `requester` when blank
        (grantee == requester is the common case; keeps subject/body naming a
        real person instead of an em-dash)
    Returns a new dict; does not mutate the input.
    """
    resolved = {k: (v or "").strip() for k, v in values.items()}

    if spec.request_type == "entrata_access" and not resolved.get("access_for"):
        resolved["access_for"] = resolved.get("requester", "")

    return resolved


def format_description(spec: RequestSpec, resolved: dict[str, str]) -> str:
    """
    Build the Freshservice Description body from collected fields.

    Plain labeled lines, one per field, in spec order. Required fields that
    are missing render as "(not provided)" so a gap is visible to the admin
    rather than silently dropped. Optional fields that are missing are omitted
    entirely.

    The returned string is what gets dropped into the draft's `description`
    before it reaches the existing dialog/mapper/submit path — nothing
    downstream changes.
    """
    lines = [spec.title, ""]
    for field in spec.fields:
        val = resolved.get(field.key, "")
        if not val:
            if not field.required:
                continue  # omit empty optional fields
            val = "(not provided)"
        lines.append(f"{field.label}: {val}")

    lines.append("")
    lines.append("— Submitted via Molli")
    return "\n".join(lines)


def build_ticket_fields(spec: RequestSpec, values: dict[str, str]) -> dict[str, Any]:
    """
    Single entry point: given collected values, return the overrides dict
    to merge into to_payload(overrides=...). Resolves values once so subject
    and description never disagree.
    """
    resolved = _resolve_values(spec, values)
    return {
        "subject": spec.subject_template.format(
            **{f.key: (resolved.get(f.key) or "—") for f in spec.fields}
        ),
        "description": format_description(spec, resolved),
        "group_id": spec.group_id,
    }
