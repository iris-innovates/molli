"""Firestore-backed per-session conversational memory for multi-turn chat.

Lets Molli handle follow-ups ("what about for Mac?" after a printer answer) by
retaining recent turns within a session. Mirrors ChunkStore's Firestore
conventions (lazy client, same project/database handling).

PRIVACY (Data Privacy guardrail):
  - Turn text is DLP-scrubbed BEFORE storage via molli_shared.guardrails.dlp.
    Raw PII is never written to Firestore -- we store DLPResult.redacted_text.
  - DLPScanner.scan() FAILS OPEN (returns raw text on a DLP outage). For
    STORAGE we override that to FAIL CLOSED: if scan_skipped is True we store
    a placeholder marker instead of the unscanned text, so a DLP outage can
    never cause raw PII to be persisted. The turn slot is preserved so the
    conversation doesn't desync; only its content is withheld.
  - `updated_at` is written so a Firestore TTL policy can expire stale
    sessions (defense-in-depth). NOTE: the TTL *policy* is project-level infra
    (Terraform / gcloud), not settable from app code -- it must be configured
    on this field separately. Scrub-before-store is the primary guarantee;
    TTL is the backstop.

SESSION KEY: keyed by `space_id` (e.g. "spaces/2twQ1yAAAAE"), which is stable
across a user's turns. For 1:1 DMs (Molli's actual usage) a space is exactly
one user<->bot, so space_id is effectively per-user. In a GROUP space, a
space_id is shared by multiple humans -- per-user memory there would need a
composite key (space_id + user_email). Documented, not handled, since Molli
runs as a DM bot.

Collection: `conversations`. Document id = sanitized space_id. Fields:
    turns: list[ {role, text, scan_skipped, ts} ]   (text = redacted)
    space_id, user_email, updated_at
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, cast

import structlog
from google.cloud import firestore

from molli_shared.guardrails.dlp import DLPScanner

log = structlog.get_logger()

_COLLECTION = "conversations"
_PLACEHOLDER = "[omitted -- PII scan unavailable]"

# Max characters of assembled history handed back for prompting. ~4 chars/token
# is the standard rough ratio, so ~4000 chars ~= ~1000 tokens of context. A
# proxy for a token budget -- bounds cost without a tokenizer dependency.
DEFAULT_CHAR_BUDGET = 4000

# Hard cap on turns kept per doc, so a long session can't grow the document
# unbounded between trims. Oldest beyond this are dropped on write.
_MAX_STORED_TURNS = 40


@dataclass
class Turn:
    role: str  # "user" or "molli"
    text: str  # DLP-redacted text, or the placeholder when scan was skipped
    scan_skipped: bool = False


def _sanitize(space_id: str) -> str:
    """Firestore doc ids can't contain '/'. space_id is 'spaces/XXXX'."""
    return space_id.replace("/", "_") or "unknown"


class ConversationStore:
    """Read/append session turns in Firestore, DLP-scrubbed before storage."""

    def __init__(
        self,
        project_id: str,
        database: str = "(default)",
        scanner: DLPScanner | None = None,
    ) -> None:
        self._client = firestore.Client(project=project_id, database=database)
        self._col = self._client.collection(_COLLECTION)
        # Reuse a scanner if provided (tests inject a fake); else construct one.
        self._scanner = scanner or DLPScanner(project_id=project_id)

    def append_turn(
        self, space_id: str, role: str, text: str, user_email: str = ""
    ) -> Turn:
        """Scrub `text` via DLP, then append it to the session doc.

        Fail-closed for storage: if the DLP scan was skipped (outage), store a
        placeholder instead of the raw text. Returns the Turn as stored.
        """
        result = self._scanner.scan(text or "")
        if result.scan_skipped:
            log.warning("conversation_scan_skipped_placeholder", space_id=space_id)
            stored = Turn(role=role, text=_PLACEHOLDER, scan_skipped=True)
        else:
            stored = Turn(role=role, text=result.redacted_text, scan_skipped=False)

        doc_id = _sanitize(space_id)
        # .document() is typed as returning the sync/async base class; this
        # store only ever uses the sync firestore.Client, so narrow it here
        # rather than letting the union type leak into every read below.
        ref = cast(firestore.DocumentReference, self._col.document(doc_id))

        @firestore.transactional
        def _txn(txn: firestore.Transaction) -> None:
            snap = ref.get(transaction=txn)
            turns: list[dict[str, Any]] = []
            if snap.exists:
                d = snap.to_dict() or {}
                turns = d.get("turns", [])
            turns.append(
                {
                    "role": stored.role,
                    "text": stored.text,
                    "scan_skipped": stored.scan_skipped,
                }
            )
            # Trim oldest beyond the hard cap.
            if len(turns) > _MAX_STORED_TURNS:
                turns = turns[-_MAX_STORED_TURNS:]
            txn.set(
                ref,
                {
                    "turns": turns,
                    "space_id": space_id,
                    "user_email": user_email,
                    "updated_at": _dt.datetime.now(_dt.timezone.utc),
                },
            )

        _txn(self._client.transaction())
        return stored

    def get_recent(
        self, space_id: str, char_budget: int = DEFAULT_CHAR_BUDGET
    ) -> list[Turn]:
        """Return recent turns whose combined text fits within char_budget.

        Newest turns are always kept; oldest are dropped first when over
        budget. Returned oldest-first (chronological) for prompt assembly.
        """
        ref = cast(firestore.DocumentReference, self._col.document(_sanitize(space_id)))
        snap = ref.get()
        if not snap.exists:
            return []
        d = snap.to_dict() or {}
        raw = d.get("turns", [])

        # Walk newest -> oldest, accumulating until the budget is hit.
        kept: list[Turn] = []
        used = 0
        for t in reversed(raw):
            text = t.get("text", "")
            cost = len(text) + len(t.get("role", "")) + 2  # role + separators
            if used + cost > char_budget and kept:
                break
            kept.append(
                Turn(
                    role=t.get("role", ""),
                    text=text,
                    scan_skipped=t.get("scan_skipped", False),
                )
            )
            used += cost
        kept.reverse()  # back to chronological
        return kept

    def clear(self, space_id: str) -> None:
        """Delete the session document, wiping all stored turns."""
        self._col.document(_sanitize(space_id)).delete()
        log.info("conversation_cleared", space_id=space_id)

    @staticmethod
    def as_transcript(turns: list[Turn]) -> str:
        """Render turns as a plain transcript for prompting."""
        lines = []
        for t in turns:
            who = "User" if t.role == "user" else "Molli"
            lines.append(f"{who}: {t.text}")
        return "\n".join(lines)
