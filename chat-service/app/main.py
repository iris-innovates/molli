"""Cloud Run entrypoint for the Molli Google Chat service.

Routes Google Chat events to the appropriate handler: guardrail chain, RAG
answer pipeline, ticket dialogs, and conversation reset.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import BackgroundTasks, FastAPI, Request
from molli_shared.clients.freshservice import FreshserviceClient
from molli_shared.clients.ticketing import (
    TicketingAuthError,
    TicketingError,
    TicketingRateLimitError,
    TicketingValidationError,
)
from molli_shared.config import get_settings
from molli_shared.conversation_store import ConversationStore
from molli_shared.guardrails.base import Action
from molli_shared.guardrails.chain import run_chain, scan_gemini_output
from molli_shared.intent import classify_intent
from molli_shared.query_rewrite import rewrite_followup
from molli_shared.schemas.factories import _fc, make_draft, make_empty_draft, make_partial_draft
from molli_shared.ticket_analysis import analyze_for_ticket
from molli_shared.topic_detection import detect_topic_change

from app.cards import dialog, form_options
from app.cards.answer_card import answer_message
from app.cards.reset_card import RESET_PROMPT_MESSAGE, reset_prompt_actions
from app.cards.structured_requests import SPECS, build_ticket_fields
from app.cards.ticket_analysis_adapter import analysis_to_draft_fields
from app.cards.ticket_mapper import build_ticket_payload
from app.cards.ticket_prefill import create_ticket_button
from app.gemini_client import FALLBACK_MESSAGE, ask_gemini
from app.tools.rag_answer import answer_with_citations, search_docs


def _classify(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (event_type, message_dict) for the Chat API event envelope."""
    chat = event.get("chat", {})

    if "appCommandPayload" in chat:
        return "APP_COMMAND", chat["appCommandPayload"].get("message", {})
    if "messagePayload" in chat:
        return "MESSAGE", chat["messagePayload"].get("message", {})
    if "addedToSpacePayload" in chat:
        return "ADDED_TO_SPACE", {}
    if "removedFromSpacePayload" in chat:
        return "REMOVED_FROM_SPACE", {}
    if "buttonClickedPayload" in chat:
        return "CARD_CLICKED", chat["buttonClickedPayload"]
    if "type" in event:
        return event["type"], event.get("message", {})
    return "UNKNOWN", {}


def _chat_reply(text: str) -> dict[str, Any]:
    """Wrap a plain text reply in the Chat API event-format response envelope."""
    return {
        "hostAppDataAction": {
            "chatDataAction": {"createMessageAction": {"message": {"text": text}}}
        }
    }


def _extract_form_inputs(event: dict[str, Any]) -> dict[str, Any]:
    """Pull dialog form values out of a SUBMIT_DIALOG event.

    Form inputs live at commonEventObject.formInputs, keyed by widget name,
    each as {"stringInputs": {"value": [...]}}. Single-value widgets return a
    one-element list; the multi-select returns all selected values. Empty
    fields come back as [''] (a list with one empty string), not [].
    """
    form_inputs = event.get("commonEventObject", {}).get("formInputs", {})

    def single(name: str) -> str:
        """First value for a single-value widget; '' if absent."""
        return str(form_inputs.get(name, {}).get("stringInputs", {}).get("value", [""])[0])

    def multi(name: str) -> list[str]:
        """All values for a multi-select; drops empty strings."""
        values = form_inputs.get(name, {}).get("stringInputs", {}).get("value", [])
        return [v for v in values if v]

    return {
        "email": single("email"),
        "subject": single("subject"),
        "affectedLocation": multi("affectedLocation"),
        "systemItem": single("systemItem"),
        "moreDetail": single("moreDetail"),
        "status": single("status"),
        "priority": single("priority"),
        "description": single("description"),
    }


def _sender_email_from_event(event: dict[str, Any]) -> str:
    """Sender email from the chat user object; '' if absent."""
    chat: dict[str, Any] = event.get("chat") or {}
    user: dict[str, Any] = chat.get("user") or {}
    return str(user.get("email") or "")


def _test_values_for(request_type: str, sender_email: str) -> dict[str, str]:
    """Hardcoded collected values for the test triggers, standing in for a
    real field-collection step. Any real implementation should return the
    same dict shape."""
    if request_type == "entrata_access":
        return {
            "requester": sender_email,
            "access_for": "Seth Hooper",
            "property": "The Forum",
            "permissions": "Add charges to ledger",
        }
    return {
        "requester": sender_email,
        "action": "remove",
        "target_user": "erin@preiss.com",
        "list_address": "novaknoxville@preiss.com",
    }


def _send_webhook_notification(
    webhook_url: str,
    category: str,
    user_email: str,
    user_name: str,
    user_message: str,
) -> None:
    import httpx

    label_map = {
        "ESCALATION_HR": "HR Escalation",
        "OSHA": "OSHA Safety Emergency",
        "HR_LEGAL": "HR/Legal Escalation",
    }
    label = label_map.get(category, "Escalation")
    text = (
        f"*{label} — Molli*\n"
        f"Employee: {user_name} ({user_email})\n"
        f'Message: "{user_message}"\n\n'
        f"Please follow up with this employee directly."
    )
    try:
        resp = httpx.post(webhook_url, json={"text": text}, timeout=10)
        resp.raise_for_status()
        log.info("webhook_notification_sent", category=category)
    except Exception as exc:  # noqa: BLE001
        log.error("webhook_notification_failed", error=str(exc), category=category)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Construct the Freshservice client once per container at startup and
    close it (and its httpx connection pool) at shutdown. Cloud Run may run
    several container instances under load; each gets its own client, which
    is correct — each manages its own connection pool.
    """
    settings = get_settings()
    app.state.ticketing = FreshserviceClient(
        base_url=settings.freshservice_base_url,
        api_key=settings.freshservice_api_key,
    )
    log.info("ticketing_client_initialized", base_url=settings.freshservice_base_url)
    app.state.conversations = ConversationStore(
        project_id=settings.gcp_project_id,
        database=settings.firestore_database,
    )
    log.info("conversation_store_initialized")

    yield
    await app.state.ticketing.aclose()
    log.info("ticketing_client_closed")


log = structlog.get_logger()
app = FastAPI(title="Molli chat-service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/")
async def chat_event(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    event = await request.json()
    event_type, message = _classify(event)
    log.info("raw_event", raw_event=event)

    if event_type == "MESSAGE":
        # Slash command arrives with the command metadata on the message.
        user_text = message.get("text", "")
        if user_text == "dialogtest":
            resp = dialog.trigger_card()
            log.info("outgoing_trigger_payload", payload=resp)
            return resp
        sender = message.get("sender", {})
        user_email = sender.get("email", "")
        user_name = sender.get("displayName", "")
        space_id = event.get("space", {}).get("name", "unknown")
        session_id = message.get("name", "unknown")

        chain_result = await run_chain(user_text, user_email, space_id, session_id)
        log.info(
            "guardrail_chain_result",
            action=chain_result.verdict.action,
            category=chain_result.verdict.category,
        )

        if not chain_result.should_call_gemini:
            verdict = chain_result.verdict
            webhook_url = get_settings().hr_escalation_webhook_url
            if (
                verdict.action == Action.ESCALATE
                and verdict.category in {"OSHA", "HR_LEGAL", "ESCALATION_HR"}
                and webhook_url
            ):
                background_tasks.add_task(
                    _send_webhook_notification,
                    webhook_url,
                    verdict.category,
                    user_email,
                    user_name,
                    user_text,
                )
            response_text = chain_result.response_to_user or ""
            if verdict.action == Action.BLOCK and verdict.category in {"FCRA", "FAIR_HOUSING"}:
                try:
                    doc_citations = search_docs(user_text)
                    if doc_citations:
                        links = "\n".join(f"- [{c.title}]({c.url})" for c in doc_citations[:2])
                        response_text = (
                            f"{response_text}\n\n"
                            f"I found these related articles in Preiss Central:\n{links}"
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("block_doc_search_failed", error=str(exc))
            return _chat_reply(response_text)

        settings = get_settings()
        show_ticket_button = False
        if settings.use_gemini:
            gemini_query = chain_result.message_to_gemini or user_text
            # Multi-turn: pull recent (DLP-scrubbed) context and rewrite a
            # follow-up into a standalone query so retrieval embeds the right
            # thing. No prior turns -> rewrite is a no-op (no extra call).
            convo = request.app.state.conversations
            _history = ConversationStore.as_transcript(convo.get_recent(space_id))
            _topic_task = asyncio.create_task(detect_topic_change(user_text, _history))
            # Intent only needs a department signal, not the standalone-rewritten
            # query, so classify concurrently with rewrite instead of waiting on
            # it -- saves up to one full LLM round trip on multi-turn replies.
            _intent_task = asyncio.create_task(classify_intent(gemini_query))
            gemini_query = await rewrite_followup(gemini_query, _history)
            intent_result = await _intent_task
            rag = answer_with_citations(gemini_query, intent=intent_result.intent)
            if not rag.no_context:
                reply_text = rag.formatted()
            else:
                show_ticket_button = True
                general = ask_gemini(gemini_query)
                _redirect_signals = ("freshservice", "preiss central")
                gemini_is_redirecting = general.strip() == FALLBACK_MESSAGE.strip() or any(
                    s in general.lower() for s in _redirect_signals
                )
                if gemini_is_redirecting:
                    reply_text = rag.text
                else:
                    disclaimer = (
                        "I couldn't find anything in Preiss Central about this, so "
                        "the following is general guidance and may not match Preiss's "
                        "actual process. Please verify or submit a Freshservice ticket "
                        "if you need the official answer.\n\n"
                    )
                    reply_text = disclaimer + general
            reply_text, _ = await scan_gemini_output(reply_text, user_email, space_id, session_id)
            topic_changed = await _topic_task
            # Persist the turn pair (DLP-scrubbed inside the store). Store the
            # RAW user_text -- memory reflects what was actually said; the
            # rewrite was only for retrieval.
            try:
                convo.append_turn(space_id, "user", user_text, user_email)
                convo.append_turn(space_id, "molli", reply_text, user_email)
            except Exception as exc:  # noqa: BLE001 -- memory must never break the reply
                log.warning("conversation_append_failed", error=str(exc))
        else:
            topic_changed = False
            reply_text = (
                f"Hi {user_name or 'there'}! I'm Molli. I'm still being built — check back soon."
            )

        if chain_result.append_to_response:
            reply_text = f"{reply_text}\n\n{chain_result.append_to_response}"
        ticket_seed = chain_result.message_to_gemini or user_text
        actions: list[dict[str, Any]] = []
        if show_ticket_button:
            actions.append(create_ticket_button(ticket_seed, user_email))
        if topic_changed:
            reply_text = f"{reply_text}\n\n{RESET_PROMPT_MESSAGE}"
            actions.extend(reset_prompt_actions())
        return answer_message(reply_text, actions=actions or None)

    if event_type == "ADDED_TO_SPACE":
        return _chat_reply(
            "Hello! I'm Molli. I'll help you find answers from Preiss Central once I'm ready."
        )

    if event_type == "CARD_CLICKED":
        # `message` here is the buttonClickedPayload (see _classify).
        common = event.get("commonEventObject", {})
        action = common.get("parameters", {}).get("actionName", "")
        log.info("card_click_received", action=action)
        if action == "openInitialDialog":
            draft_type = common.get("parameters", {}).get(
                "draftType", ""
            )  # however you read action params
            draft = {
                "full": make_draft,
                "partial": make_partial_draft,
                "empty": make_empty_draft,
            }.get(draft_type, make_draft)()
            return dialog.open_dialog(draft)

        if action == "submitNameDialog":
            inputs = _extract_form_inputs(event)
            # Group isn't a visible widget — it travels as a hidden Submit
            # button parameter set in dialog.open_dialog (Molli's guess, or
            # the fallback group). See form_options.FALLBACK_GROUP.
            inputs["group"] = common.get("parameters", {}).get("groupId") or str(
                form_options.FALLBACK_GROUP["id"]
            )
            log.info("dialog_submit_received", inputs=inputs)

            # Build + validate the payload. Strict schema raises on bad data.
            try:
                payload = build_ticket_payload(inputs)
            except Exception as exc:
                log.warning("ticket_payload_build_failed", error=str(exc))
                return dialog.submit_notification(
                    "Something was wrong with the ticket details. Please check your entries and try again."
                )

            settings = get_settings()
            if settings.freshservice_dry_run:
                # DRY RUN: log exactly what would be sent, create nothing.
                log.info(
                    "ticket_dry_run",
                    payload=payload.model_dump(exclude_none=True),
                )
                return dialog.submit_notification(
                    "Dry run: ticket payload built and validated (not sent)."
                )

            # LIVE: create the ticket.
            try:
                created = await request.app.state.ticketing.create_ticket(payload)
                log.info("ticket_created", ticket_id=created.id)
                return dialog.submit_notification(f"#{created.id}.")
            except TicketingValidationError as exc:
                log.warning("ticket_validation_error", error=str(exc))
                return dialog.submit_notification(
                    "The ticketing system rejected the ticket. Please check your entries."
                )
            except (TicketingAuthError, TicketingRateLimitError, TicketingError) as exc:
                log.error("ticket_create_failed", error=str(exc))
                return dialog.submit_notification(
                    "Couldn't reach the ticketing system right now. Please try again shortly."
                )

        if action == "analyzeForTicket":
            params = common.get("parameters", {})
            user_email = params.get("userEmail", "") or _sender_email_from_event(event)
            user_question = params.get("userQuestion", "")
            space_id = event.get("space", {}).get("name", "unknown")
            history = request.app.state.conversations.get_recent(space_id)
            analysis = await analyze_for_ticket(history, user_question)
            fields = analysis_to_draft_fields(analysis)
            draft = make_draft(
                conversation_id=space_id,
                email=_fc(user_email, 0.99, "user-stated"),
                **fields,
            )
            return dialog.open_dialog(draft)

        if action == "buildSmartTicket":
            params = common.get("parameters", {})
            user_email = params.get("userEmail", "") or _sender_email_from_event(event)
            user_question = params.get("userQuestion", "")
            space_id = event.get("space", {}).get("name", "unknown")
            history = request.app.state.conversations.get_recent(space_id)
            analysis = await analyze_for_ticket(history, user_question)
            fields = analysis_to_draft_fields(analysis)
            draft = make_draft(
                conversation_id=space_id,
                email=_fc(user_email, 0.99, "user-stated"),
                **fields,
            )
            return dialog.open_dialog(draft)

        if action == "openStructuredDialog":
            request_type = common.get("parameters", {}).get("requestType", "")
            spec = SPECS.get(request_type)
            if spec is None:
                log.warning("unknown_request_type", request_type=request_type)
                return {}

            sender_email = _sender_email_from_event(event)
            collected = _test_values_for(request_type, sender_email)
            fields = build_ticket_fields(spec, collected)  # subject, description, group_id

            draft = make_draft(
                subject=_fc(fields["subject"]),
                description=_fc(fields["description"]),
                group_id=_fc(fields["group_id"]),
            )

            return dialog.open_dialog(draft)

        if action == "resetHistory":
            space_id = event.get("space", {}).get("name", "unknown")
            try:
                request.app.state.conversations.clear(space_id)
                log.info("conversation_reset", space_id=space_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("conversation_reset_failed", error=str(exc))
            return _chat_reply("Done — conversation history cleared. What would you like to know?")

        if action == "keepHistory":
            return _chat_reply("Got it — keeping your conversation history.")

        log.info("unhandled_card_click", action=action)
        return {}

    return {}
