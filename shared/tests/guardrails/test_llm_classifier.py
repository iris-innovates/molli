"""Tests for FHAFCRAClassifier and _classify.

This classifier is FHA-only: FCRA-flavored language (screening, background
checks, adverse action, etc.) is classified NONE here and handled instead by
the separate regex-based FCRAGuardrail — see test_fcra.py.

Two layers:
  - Guardrail-class tests patch _classify with AsyncMock — no GCP calls,
    verify that the right verdict/category/canned_response comes back.
  - _classify unit tests patch get_settings + _call_gemini — exercise every
    code path (FHA, NONE, garbage response, exception, timeout,
    use_gemini=False, settings unavailable).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from molli_shared.guardrails.base import Action
from molli_shared.guardrails.llm_classifier import FHAFCRAClassifier, _classify

USER = "test@preiss.com"
classifier = FHAFCRAClassifier()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_settings(*, use_gemini: bool = True) -> MagicMock:
    s = MagicMock()
    s.use_gemini = use_gemini
    s.gcp_project_id = "test-project"
    s.gcp_region = "us-central1"
    s.gemini_model = "gemini-2.5-flash"
    return s


# ---------------------------------------------------------------------------
# Guardrail class — _classify patched, no GCP calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guardrail_blocks_fha_topic():
    with patch(
        "molli_shared.guardrails.llm_classifier._classify",
        new=AsyncMock(return_value="FHA"),
    ):
        verdict = await classifier.check(
            "do we have to rent to everyone regardless of where they come from?", USER
        )
    assert verdict.action == Action.BLOCK
    assert verdict.category == "FAIR_HOUSING"
    assert verdict.canned_response is not None
    assert "HR" in verdict.canned_response


@pytest.mark.asyncio
async def test_guardrail_allows_unrelated_topic():
    with patch(
        "molli_shared.guardrails.llm_classifier._classify",
        new=AsyncMock(return_value="NONE"),
    ):
        verdict = await classifier.check(
            "how do I reset my Google Workspace password?", USER
        )
    assert verdict.action == Action.ALLOW


# ---------------------------------------------------------------------------
# _classify — get_settings + _call_gemini patched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_returns_fha():
    with (
        patch(
            "molli_shared.guardrails.llm_classifier.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "molli_shared.guardrails.llm_classifier._call_gemini",
            return_value="FHA",
        ),
    ):
        assert (
            await _classify("can we refuse to rent based on someone's background?")
            == "FHA"
        )


@pytest.mark.asyncio
async def test_classify_normalises_fcra_response_to_none():
    # The system prompt asks the model for FHA/NONE only; if it ever returns
    # FCRA anyway (old prompt behavior, or model drift), _classify falls back
    # to NONE since "FCRA" isn't in _VALID_TOPICS.
    with (
        patch(
            "molli_shared.guardrails.llm_classifier.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "molli_shared.guardrails.llm_classifier._call_gemini",
            return_value="FCRA",
        ),
    ):
        assert (
            await _classify("how do we handle it when the report comes back clean?")
            == "NONE"
        )


@pytest.mark.asyncio
async def test_classify_returns_none():
    with (
        patch(
            "molli_shared.guardrails.llm_classifier.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "molli_shared.guardrails.llm_classifier._call_gemini",
            return_value="NONE",
        ),
    ):
        assert await _classify("how do I request PTO?") == "NONE"


@pytest.mark.asyncio
async def test_classify_normalises_garbage_response():
    """An unexpected token from the model falls back to NONE (fail-open)."""
    with (
        patch(
            "molli_shared.guardrails.llm_classifier.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "molli_shared.guardrails.llm_classifier._call_gemini",
            return_value="MAYBE I SHOULD ANSWER",
        ),
    ):
        assert await _classify("something ambiguous") == "NONE"


@pytest.mark.asyncio
async def test_classify_fails_open_on_gemini_exception():
    """A Gemini or network error returns NONE so normal traffic is unaffected."""
    with (
        patch(
            "molli_shared.guardrails.llm_classifier.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "molli_shared.guardrails.llm_classifier._call_gemini",
            side_effect=RuntimeError("GCP unavailable"),
        ),
    ):
        assert await _classify("any message") == "NONE"


@pytest.mark.asyncio
async def test_classify_fails_open_on_timeout():
    """asyncio.TimeoutError from wait_for is caught and returns NONE."""
    with (
        patch(
            "molli_shared.guardrails.llm_classifier.get_settings",
            return_value=_mock_settings(),
        ),
        patch(
            "molli_shared.guardrails.llm_classifier._call_gemini",
            side_effect=asyncio.TimeoutError,
        ),
    ):
        assert await _classify("any message") == "NONE"


@pytest.mark.asyncio
async def test_classify_skipped_when_use_gemini_false():
    """Classifier short-circuits without a GCP call when use_gemini=False."""
    with (
        patch(
            "molli_shared.guardrails.llm_classifier.get_settings",
            return_value=_mock_settings(use_gemini=False),
        ),
        patch(
            "molli_shared.guardrails.llm_classifier._call_gemini",
        ) as mock_call,
    ):
        result = await _classify("can we look at their criminal record?")
    assert result == "NONE"
    mock_call.assert_not_called()


@pytest.mark.asyncio
async def test_classify_fails_open_when_settings_unavailable():
    """Missing GCP env vars (KeyError from get_settings) returns NONE."""
    with patch(
        "molli_shared.guardrails.llm_classifier.get_settings",
        side_effect=KeyError("GCP_PROJECT_ID"),
    ):
        assert await _classify("any message") == "NONE"
