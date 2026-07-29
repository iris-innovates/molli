"""Generic Gemini Q&A client for chat-service.

Wraps the Vertex AI GenerativeModel in a single ask() call: user text in,
model text out. No tools, no RAG, no D360 retrieval — that's downstream work.
Auth is application-default credentials via vertexai.init(); no new secrets
required.
"""

from __future__ import annotations

import structlog
import vertexai
from molli_shared.config import get_settings
from molli_shared.vertex_retry import vertex_retry
from vertexai.generative_models import GenerationConfig, GenerationResponse, GenerativeModel

log = structlog.get_logger()

# Short general-purpose system prompt, used only when RAG has no context.
# The "say so if you don't know" line is deliberate — it reduces confident
# hallucination about internal Preiss policy while we have no grounding yet.
SYSTEM_INSTRUCTION = (
    "You are Molli, Preiss's AI-powered employee assistant. "
    "You help employees with IT, Operations, and HR questions in a friendly, "
    "concise, professional tone. "
    "You are not yet connected to Preiss's internal knowledge base, so if you "
    "are asked about something specific to Preiss — a particular policy, system, "
    "person, property, or internal process — say you don't have that information "
    "yet and suggest the employee submit a Freshservice ticket or check Preiss "
    "Central. Do not guess at internal Preiss details. "
    "For general questions you can answer from your own knowledge, just answer helpfully."
)

FALLBACK_MESSAGE = (
    "Sorry — I'm having trouble generating a response right now. "
    "Please try again in a moment, or submit a Freshservice ticket if it's urgent."
)

_model: GenerativeModel | None = None


def _get_model() -> GenerativeModel:
    """Lazily build (and cache) the GenerativeModel.

    vertexai.init() is idempotent; we initialize on first use rather than at
    import time so tests and the placeholder path don't require GCP creds.
    """
    global _model
    if _model is None:
        settings = get_settings()
        vertexai.init(project=settings.gcp_project_id, location=settings.gcp_region)
        _model = GenerativeModel(
            model_name=settings.gemini_model,
            system_instruction=SYSTEM_INSTRUCTION,
        )
    return _model


@vertex_retry  # type: ignore[untyped-decorator]
def _generate(model: GenerativeModel, prompt: str, temperature: float) -> GenerationResponse:
    return model.generate_content(
        prompt, generation_config=GenerationConfig(temperature=temperature)
    )


def ask_gemini(user_text: str) -> str:
    """Send user_text to Gemini and return the model's text reply.

    Returns FALLBACK_MESSAGE on any error or empty response rather than
    raising, so the Chat handler can always return a valid reply.
    """
    if not user_text.strip():
        return (
            "Hi! I'm Molli. Ask me an IT, Operations, or HR question and I'll do my best to help."
        )

    settings = get_settings()
    try:
        model = _get_model()
        response = _generate(model, user_text, settings.gemini_temperature)
        text = (response.text or "").strip()
        if not text:
            log.warning("gemini_empty_response")
            return FALLBACK_MESSAGE
        return text
    except Exception as exc:  # noqa: BLE001 — never let a Gemini error break the Chat reply
        log.error("gemini_call_failed", error=str(exc))
        return FALLBACK_MESSAGE
