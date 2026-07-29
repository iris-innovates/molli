"""Unit tests for department intent classification.

Patches intent._call_gemini so these run without GCP creds (same approach as
the guardrail classifier tests). Covers each department, ambiguous/general,
malformed model output, and the fail-open paths.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from molli_shared import intent
from molli_shared.intent import classify_intent


def _mock_reply(intent_label: str, confidence: float) -> str:
    return json.dumps({"intent": intent_label, "confidence": confidence})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,confidence",
    [("IT", 0.95), ("HR", 0.9), ("Ops", 0.92), ("general", 0.3)],
)
async def test_each_department(label, confidence):
    with patch.object(
        intent, "_call_gemini", return_value=_mock_reply(label, confidence)
    ):
        with patch.object(intent, "get_settings") as gs:
            gs.return_value.use_gemini = True
            gs.return_value.gcp_project_id = "p"
            gs.return_value.gcp_region = "us-central1"
            gs.return_value.gemini_model = "gemini-2.5-flash"
            result = await classify_intent("some query")
    assert result.intent == label
    assert result.confidence == confidence


@pytest.mark.asyncio
async def test_general_has_no_group():
    with patch.object(intent, "_call_gemini", return_value=_mock_reply("general", 0.2)):
        with patch.object(intent, "get_settings") as gs:
            gs.return_value.use_gemini = True
            gs.return_value.gcp_project_id = "p"
            gs.return_value.gcp_region = "us-central1"
            gs.return_value.gemini_model = "gemini-2.5-flash"
            result = await classify_intent("what's the weather")
    assert result.intent == "general"
    assert result.is_confident is False


@pytest.mark.asyncio
async def test_low_confidence_department_not_confident():
    # A department label but below the LOW_CONFIDENCE threshold.
    with patch.object(intent, "_call_gemini", return_value=_mock_reply("Ops", 0.3)):
        with patch.object(intent, "get_settings") as gs:
            gs.return_value.use_gemini = True
            gs.return_value.gcp_project_id = "p"
            gs.return_value.gcp_region = "us-central1"
            gs.return_value.gemini_model = "gemini-2.5-flash"
            result = await classify_intent("vague thing")
    assert result.intent == "Ops"
    assert result.is_confident is False  # below 0.5 threshold


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_parsed():
    fenced = "```json\n" + _mock_reply("HR", 0.88) + "\n```"
    with patch.object(intent, "_call_gemini", return_value=fenced):
        with patch.object(intent, "get_settings") as gs:
            gs.return_value.use_gemini = True
            gs.return_value.gcp_project_id = "p"
            gs.return_value.gcp_region = "us-central1"
            gs.return_value.gemini_model = "gemini-2.5-flash"
            result = await classify_intent("how much PTO do I get")
    assert result.intent == "HR"
    assert result.confidence == 0.88


@pytest.mark.asyncio
async def test_malformed_json_fails_open_to_general():
    with patch.object(intent, "_call_gemini", return_value="not json at all"):
        with patch.object(intent, "get_settings") as gs:
            gs.return_value.use_gemini = True
            gs.return_value.gcp_project_id = "p"
            gs.return_value.gcp_region = "us-central1"
            gs.return_value.gemini_model = "gemini-2.5-flash"
            result = await classify_intent("anything")
    assert result.intent == "general"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_invalid_intent_value_fails_open():
    with patch.object(
        intent, "_call_gemini", return_value=_mock_reply("Marketing", 0.9)
    ):
        with patch.object(intent, "get_settings") as gs:
            gs.return_value.use_gemini = True
            gs.return_value.gcp_project_id = "p"
            gs.return_value.gcp_region = "us-central1"
            gs.return_value.gemini_model = "gemini-2.5-flash"
            result = await classify_intent("anything")
    assert result.intent == "general"  # 'Marketing' not in VALID_INTENTS


@pytest.mark.asyncio
async def test_empty_message_is_general():
    result = await classify_intent("   ")
    assert result.intent == "general"
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_use_gemini_disabled_fails_open():
    with patch.object(intent, "get_settings") as gs:
        gs.return_value.use_gemini = False
        result = await classify_intent("reset my password")
    assert result.intent == "general"


@pytest.mark.asyncio
async def test_confidence_clamped():
    with patch.object(intent, "_call_gemini", return_value=_mock_reply("IT", 1.7)):
        with patch.object(intent, "get_settings") as gs:
            gs.return_value.use_gemini = True
            gs.return_value.gcp_project_id = "p"
            gs.return_value.gcp_region = "us-central1"
            gs.return_value.gemini_model = "gemini-2.5-flash"
            result = await classify_intent("x")
    assert result.confidence == 1.0  # clamped to [0,1]
