"""Tests for per-session conversational memory + follow-up rewriting.

No GCP: ConversationStore takes an injected fake Firestore client and a fake
DLP scanner; query_rewrite patches _call_gemini. Covers the exit criteria:
multi-turn retention (3+ turns), bounded/trimmed context, DLP scrub-before-
store + fail-closed placeholder, and follow-up rewrite behavior.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from molli_shared import query_rewrite
from molli_shared.conversation_store import (
    ConversationStore,
    _PLACEHOLDER,
)
from molli_shared.guardrails.dlp import DLPResult
from molli_shared.query_rewrite import rewrite_followup


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class _FakeScanner:
    """Stand-in for DLPScanner. Redacts 'SECRET' -> '[REDACTED]'; can be set
    to simulate a DLP outage (scan_skipped=True, raw text returned)."""

    def __init__(self, skip: bool = False):
        self.skip = skip

    def scan(self, text: str) -> DLPResult:
        if self.skip:
            return DLPResult(
                original_text=text,
                redacted_text=text,
                scan_skipped=True,
                skip_reason="simulated outage",
            )
        redacted = text.replace("SECRET", "[REDACTED]")
        return DLPResult(
            original_text=text, redacted_text=redacted, has_pii=(redacted != text)
        )


class _FakeDoc:
    def __init__(self, store, doc_id):
        self._store = store
        self._id = doc_id

    def get(self, transaction=None):
        return _FakeSnap(self._store._data.get(self._id))

    def set(self, data):
        self._store._data[self._id] = data


class _FakeSnap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return self._data


class _FakeTxn:
    def __init__(self, client):
        self._client = client

    def set(self, ref, data):
        # Real firestore.Transaction.set(ref, data) writes through to the doc.
        ref.set(data)

    def get(self, ref):
        return ref.get()


class _FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, doc_id):
        return _FakeDoc(self._store, doc_id)


class _FakeFirestore:
    """Minimal in-memory Firestore double supporting the store's usage."""

    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}

    def collection(self, name):
        return _FakeCollection(self)

    def transaction(self):
        return _FakeTxn(self)


def _make_store(skip_dlp: bool = False) -> ConversationStore:
    """Build a ConversationStore wired to fakes (no GCP)."""
    store = ConversationStore.__new__(ConversationStore)
    fake = _FakeFirestore()
    store._client = fake
    store._col = fake.collection("conversations")
    store._scanner = _FakeScanner(skip=skip_dlp)
    return store


# firestore.transactional decorator: in real code it wraps the inner fn. Our
# fake _txn just needs the inner function to run with our fake transaction.
@pytest.fixture(autouse=True)
def _patch_transactional():
    import molli_shared.conversation_store as cs

    def _passthrough(fn):
        def wrapper(txn):
            return fn(txn)

        return wrapper

    with patch.object(cs.firestore, "transactional", _passthrough):
        yield


# --------------------------------------------------------------------------
# Multi-turn retention (3+ turns) -- the headline exit criterion
# --------------------------------------------------------------------------
def test_three_turn_conversation_retained():
    store = _make_store()
    sid = "spaces/ABC"
    store.append_turn(sid, "user", "How do I connect to the office printer?")
    store.append_turn(sid, "molli", "Open the printer settings and add it by IP.")
    store.append_turn(sid, "user", "What about for Mac?")

    turns = store.get_recent(sid)
    assert len(turns) == 3
    assert turns[0].role == "user"
    assert "printer" in turns[0].text
    assert turns[2].text == "What about for Mac?"
    # chronological order preserved
    assert [t.role for t in turns] == ["user", "molli", "user"]


def test_transcript_rendering():
    store = _make_store()
    sid = "spaces/X"
    store.append_turn(sid, "user", "hello")
    store.append_turn(sid, "molli", "hi there")
    transcript = ConversationStore.as_transcript(store.get_recent(sid))
    assert "User: hello" in transcript
    assert "Molli: hi there" in transcript


# --------------------------------------------------------------------------
# DLP scrub-before-store
# --------------------------------------------------------------------------
def test_pii_is_scrubbed_before_storage():
    store = _make_store()
    sid = "spaces/PII"
    stored = store.append_turn(sid, "user", "my code is SECRET please help")
    assert "SECRET" not in stored.text
    assert "[REDACTED]" in stored.text
    # and it's the scrubbed text that persists
    assert "SECRET" not in store.get_recent(sid)[0].text


def test_dlp_skip_stores_placeholder_not_raw():
    store = _make_store(skip_dlp=True)  # simulate DLP outage
    sid = "spaces/OUT"
    stored = store.append_turn(sid, "user", "my SECRET is 123-45-6789")
    # fail-CLOSED: raw text must NOT be stored; placeholder instead
    assert stored.text == _PLACEHOLDER
    assert stored.scan_skipped is True
    assert "123-45-6789" not in store.get_recent(sid)[0].text


# --------------------------------------------------------------------------
# Bounded / trimmed context window
# --------------------------------------------------------------------------
def test_context_trimmed_to_char_budget():
    store = _make_store()
    sid = "spaces/LONG"
    # 10 turns of ~100 chars each = ~1000 chars
    for i in range(10):
        store.append_turn(sid, "user", f"turn {i} " + "x" * 100)

    # Small budget should keep only the most recent few turns.
    turns = store.get_recent(sid, char_budget=250)
    assert len(turns) < 10
    # newest turn must always be present
    assert "turn 9" in turns[-1].text
    # total kept text within budget (allowing the +role/separator overhead)
    total = sum(len(t.text) for t in turns)
    assert total <= 250


def test_get_recent_empty_for_unknown_session():
    store = _make_store()
    assert store.get_recent("spaces/NOPE") == []


# --------------------------------------------------------------------------
# Follow-up query rewriting
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rewrite_skipped_when_no_history():
    # No history -> returns unchanged, NO Gemini call.
    with patch.object(query_rewrite, "_call_gemini") as called:
        out = await rewrite_followup("What about for Mac?", history="")
    assert out == "What about for Mac?"
    called.assert_not_called()


@pytest.mark.asyncio
async def test_rewrite_expands_followup_with_history():
    history = "User: How do I connect to the office printer?\nMolli: Add it by IP."
    rewritten = "How do I connect to the office printer on a Mac?"
    with patch.object(query_rewrite, "_call_gemini", return_value=rewritten):
        with patch.object(query_rewrite, "get_settings") as gs:
            gs.return_value.use_gemini = True
            gs.return_value.gcp_project_id = "p"
            gs.return_value.gcp_region = "us-central1"
            gs.return_value.gemini_model = "gemini-2.5-flash"
            out = await rewrite_followup("What about for Mac?", history=history)
    assert out == rewritten


@pytest.mark.asyncio
async def test_rewrite_fails_safe_to_original_on_error():
    history = "User: something\nMolli: reply"
    with patch.object(query_rewrite, "_call_gemini", side_effect=RuntimeError("boom")):
        with patch.object(query_rewrite, "get_settings") as gs:
            gs.return_value.use_gemini = True
            gs.return_value.gcp_project_id = "p"
            gs.return_value.gcp_region = "us-central1"
            gs.return_value.gemini_model = "gemini-2.5-flash"
            out = await rewrite_followup("what about mobile?", history=history)
    assert out == "what about mobile?"  # unchanged on failure
