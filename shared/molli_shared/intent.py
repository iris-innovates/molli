"""Department intent classification for incoming employee queries.

Classifies each query into one of {HR, IT, Ops, general} with a confidence
value, so retrieval can be scoped (soft boost) and any created ticket can be
routed to the right Freshservice group.

Zero/few-shot via Gemini (temperature 0) -- no separately trained model at
this stage. Mirrors the conventions of guardrails/llm_classifier.py:
- _call_gemini isolated as a named function so tests patch it directly
- asyncio.to_thread + timeout wrapper
- FAIL-OPEN: any error/timeout returns intent='general', confidence=0.0, so a
  classifier outage never blocks a user (retrieval just stays unscoped and the
  ticket is not auto-routed)
- skipped (returns general) when settings.use_gemini is False (local/CI)

Confidence is the MODEL'S SELF-ESTIMATE, not a calibrated probability. Use it
as a routing threshold (low confidence -> treat as general / let fallback
handle it), not as a statistical guarantee.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import structlog
import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from molli_shared.config import get_settings

log = structlog.get_logger()

_CLASSIFY_TIMEOUT = 2.0  # seconds; fail-open on breach

# Below this confidence we treat the result as 'general' for routing purposes,
# feeding the no-context / general fallback rather than scoping hard.
LOW_CONFIDENCE = 0.5

VALID_INTENTS = {"HR", "IT", "Ops", "general"}

# Ticket-category routing is intentionally NOT defined here. Freshservice
# group routing already lives in chat-service/app/cards/structured_requests.py,
# where each RequestSpec carries a real, confirmed group_id. Duplicating a
# department->group map here would invite drift. The classifier returns intent +
# confidence only; routing consumers map intent to a group at the routing layer.

_SYSTEM_PROMPT = (
    "You are an intent classifier for The Preiss Company's internal employee "
    "assistant (Molli). Classify the employee's message into exactly one "
    "department, based on who would own the answer:\n"
    "\n"
    "IT  - technology: Google/Gmail accounts, passwords, login, printers, "
    "VPN, Wi-Fi, email/Mimecast, hardware/laptops, software, distribution "
    "lists, computer issues.\n"
    "HR  - people: benefits, PTO/leave, payroll, onboarding, employee "
    "handbook, conduct, job changes, compensation.\n"
    "Ops - property operations: Entrata, resident portals, leases, ledgers/"
    "charges/refunds, screening, move-ins/outs, property settings, utilities, "
    "office hours, property management systems.\n"
    "general - anything that doesn't clearly belong to one department, is "
    "general knowledge, social, or too vague to tell.\n"
    "\n"
    "Respond with ONLY a JSON object, no markdown, no prose, of the form:\n"
    '{"intent": "IT", "confidence": 0.0}\n'
    "where intent is one of IT, HR, Ops, general and confidence is your "
    "certainty from 0.0 to 1.0. Use 'general' with low confidence when unsure."
)

_USER_PROMPT = "Employee message: {message}"


@dataclass
class IntentResult:
    """Classified department intent plus the model's self-estimated confidence."""

    intent: str  # one of VALID_INTENTS
    confidence: float  # 0.0 - 1.0, model self-estimate (NOT calibrated)

    @property
    def is_confident(self) -> bool:
        return self.confidence >= LOW_CONFIDENCE and self.intent != "general"


_FALLBACK = IntentResult(intent="general", confidence=0.0)


def _call_gemini(project_id: str, region: str, model_name: str, text: str) -> str:
    """Synchronous Gemini call -- runs inside asyncio.to_thread.

    Isolated as a named function so tests can patch it without touching the
    async plumbing (same pattern as guardrails/llm_classifier.py).
    """
    vertexai.init(project=project_id, location=region)
    model = GenerativeModel(model_name=model_name, system_instruction=_SYSTEM_PROMPT)
    response = model.generate_content(
        _USER_PROMPT.format(message=text),
        generation_config=GenerationConfig(temperature=0.0),
    )
    return (response.text or "").strip()


def _parse(raw: str) -> IntentResult:
    """Parse Gemini's JSON reply into an IntentResult. Fail-open to general.

    Tolerates markdown code fences and stray text around the JSON object.
    """
    text = raw.strip()
    # Strip ```json fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    # Grab the outermost JSON object if there's surrounding prose.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
        intent = str(data.get("intent", "general"))
        confidence = float(data.get("confidence", 0.0))
    except (json.JSONDecodeError, ValueError, TypeError):
        log.warning("intent_parse_failed", raw=raw[:200])
        return _FALLBACK
    if intent not in VALID_INTENTS:
        log.warning("intent_invalid_value", intent=intent)
        return _FALLBACK
    # Clamp confidence to [0, 1].
    confidence = max(0.0, min(1.0, confidence))
    return IntentResult(intent=intent, confidence=confidence)


async def classify_intent(message: str) -> IntentResult:
    """Classify a query into {HR, IT, Ops, general} + confidence.

    Fails open to IntentResult('general', 0.0) on any error, timeout, missing
    GCP config, or when use_gemini is disabled -- so classification never
    blocks the user; downstream just treats it as unscoped/general.
    """
    if not message or not message.strip():
        return _FALLBACK

    try:
        settings = get_settings()
    except Exception:
        return _FALLBACK  # no GCP env -- fail-open

    if not settings.use_gemini:
        return _FALLBACK

    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                _call_gemini,
                settings.gcp_project_id,
                settings.gcp_region,
                settings.gemini_model,
                message,
            ),
            timeout=_CLASSIFY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return _FALLBACK
    except Exception as exc:  # noqa: BLE001
        log.error("intent_classifier_error", error=str(exc))
        return _FALLBACK

    result = _parse(raw)
    return result
