"""Topic-change detection for session reset prompting.

When a user's new message is clearly about a different topic than the recent
conversation history, Molli offers to clear the history so prior context
doesn't bleed into the new thread.

Mirrors query_rewrite.py conventions: temp-0 Gemini, asyncio.to_thread +
timeout, fail-safe (returns False on any error -- better to skip the prompt
than to interrupt the flow with a false positive).

Conservative by design: only returns True when the shift is unambiguous.
Ambiguous or borderline cases return False.
"""

from __future__ import annotations

import asyncio

import structlog
import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel

from molli_shared.config import get_settings

log = structlog.get_logger()

_DETECTION_TIMEOUT = 1.5

_SYSTEM_PROMPT = (
    "You detect whether a user's new message is about a completely different "
    "topic from the recent conversation history.\n"
    "Rules:\n"
    "1. Answer ONLY with 'new_topic' or 'follow_up' — nothing else.\n"
    "2. Only answer 'new_topic' when the shift is unambiguous (e.g. history is "
    "about printer setup, new message is about payroll). When in doubt, "
    "answer 'follow_up'.\n"
    "3. If there is no history, answer 'follow_up'.\n"
    "4. Short acknowledgements ('ok', 'thanks', 'got it') are 'follow_up', "
    "not new topics."
)

_USER_TEMPLATE = "Recent conversation:\n{history}\n\nNew message: {query}\n\nAnswer:"


def _call_gemini(
    project_id: str, region: str, model_name: str, history: str, query: str
) -> bool:
    """Synchronous Gemini call -- runs inside asyncio.to_thread."""
    vertexai.init(project=project_id, location=region)
    model = GenerativeModel(model_name=model_name, system_instruction=_SYSTEM_PROMPT)
    response = model.generate_content(
        _USER_TEMPLATE.format(history=history, query=query),
        generation_config=GenerationConfig(temperature=0.0),
    )
    return (response.text or "").strip().lower() == "new_topic"


async def detect_topic_change(query: str, history: str) -> bool:
    """Return True if query is clearly a new topic vs. history. Fail-safe to False.

    Returns False immediately when there is no history (nothing to diverge
    from), or on any error/timeout. Never raises, never blocks.
    """
    if not query or not query.strip():
        return False
    if not history or not history.strip():
        return False  # first turn -- no prior context, nothing to detect

    try:
        settings = get_settings()
    except Exception:
        return False
    if not settings.use_gemini:
        return False

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                _call_gemini,
                settings.gcp_project_id,
                settings.gcp_region,
                settings.gemini_model,
                history,
                query,
            ),
            timeout=_DETECTION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("topic_detection_error", error=str(exc))
        return False

    log.info("topic_detection_result", is_new_topic=result)
    return result
