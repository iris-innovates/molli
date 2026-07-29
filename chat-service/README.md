# chat-service

FastAPI app that handles Google Chat events for Molli. Deployed as a Cloud Run service (see [`Dockerfile`](Dockerfile) and `.github/workflows/deploy-chat-service.yml` at the repo root). Depends on the [`shared`](../shared/README.md) package for clients, guardrails, and schemas.

## Request flow

Single entrypoint: `POST /` in [`app/main.py`](app/main.py), handling the Google Chat event envelope. `GET /health` is a plain liveness check.

For a `MESSAGE` event:

1. **Classify** the event (`_classify`) into `MESSAGE` / `CARD_CLICKED` / `ADDED_TO_SPACE` / etc.
2. **Guardrail chain** (`run_chain`, from `shared`) runs on the raw text first. `BLOCK`/`ESCALATE` short-circuits: no Gemini call, a canned response goes back (with an optional HR/OSHA escalation webhook fired via `BackgroundTasks`), and — for FCRA/Fair Housing blocks — a doc search still runs to surface related Preiss Central articles alongside the canned refusal.
3. If the chain allows it: pull recent conversation history from `ConversationStore` (Firestore), then **concurrently** kick off topic-change detection and intent classification while the query gets rewritten into a standalone form for multi-turn follow-ups.
4. **RAG answer** (`app/tools/rag_answer.py::answer_with_citations`) embeds the query, queries Vector Search, fetches chunk text from Firestore, and asks Gemini to answer only from those sources, citing inline as `[1]`, `[2]`.
5. If RAG has no context (empty retrieval or the model emits the `INSUFFICIENT_CONTEXT` sentinel), fall back to a general Gemini answer (`app/gemini_client.py`) with a disclaimer, and show a **Create Ticket** button.
6. Gemini's output is scanned again (`scan_gemini_output`, Data Privacy Mode B) before being persisted to conversation memory and returned.
7. Response is wrapped as a `cardsV2` message (`app/cards/answer_card.py`), with a topic-reset prompt appended if the topic changed mid-conversation.

For a `CARD_CLICKED` event, `main.py` dispatches on the button's `actionName`: opening the ticket dialog (plain, AI-drafted, or structured-request variants), submitting it (dry-run or live Freshservice ticket creation), or handling the reset-history / keep-history buttons.

## Layout

```
app/
  main.py                     FastAPI app, event router, lifespan (Freshservice client + ConversationStore)
  gemini_client.py            Generic ungrounded Gemini Q&A fallback (ask_gemini)
  tools/
    rag_answer.py             RAG pipeline: embed -> Vector Search -> Firestore chunk fetch -> cited Gemini answer
    rag_latency_check.py      Manual latency benchmark script (not part of the request path)
  cards/
    answer_card.py            Builds the cardsV2 reply (answer text + citations)
    text.py                   Markdown -> Chat's limited textParagraph HTML subset
    dialog.py                 Ticket-dialog card/open/submit builders
    form_options.py           Static dropdown vocabularies for the ticket dialog (must match exactly, or the pre-fill silently fails)
    ticket_mapper.py           Dialog form inputs -> TicketCreatePayload (user-fills-every-field path)
    ticket_prefill.py          "Create Ticket" button pre-filled from the user's unanswered question
    ticket_analysis_adapter.py TicketAnalysis (shared) -> make_draft() kwargs, for the AI-drafted ticket path
    structured_requests.py     Field specs for structured admin requests (e.g. Entrata access, distribution-list changes) routed to clean tickets
    reset_card.py              Buttons shown when Molli detects a topic change mid-conversation
```

## Running locally

```bash
uv sync --all-packages          # from repo root
cd chat-service
uv run uvicorn app.main:app --reload --port 8080
```

Required env vars (see `shared/molli_shared/config.py` for the full `Settings` model) — non-secret values in `.env`, secrets from GCP Secret Manager at runtime:

| Var | Notes |
|---|---|
| `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER` | required |
| `GCP_REGION` | default `us-central1` |
| `FRESHSERVICE_DOMAIN` | tenant subdomain, e.g. `tpco-org` |
| `FRESHSERVICE_API_KEY` | required — real key, normally injected from Secret Manager in deployed envs |
| `FRESHSERVICE_DRY_RUN` | when true, ticket submission logs the payload instead of calling Freshservice |
| `VECTOR_INDEX_ID`, `VECTOR_INDEX_ENDPOINT` | Vertex AI Vector Search index/endpoint for RAG |
| `MOLLI_USE_GEMINI` | kill switch — when false, replies with a static placeholder instead of calling Gemini |
| `GEMINI_MODEL` | default `gemini-2.5-flash` |
| `HR_ESCALATION_WEBHOOK_URL` | optional Google Chat incoming webhook for OSHA/HR-Legal escalations |
| `CHAT_SERVICE_URL` | this service's own Cloud Run URL, used as the expected Google Chat JWT audience |

There is no Google Chat request-signature verification wired into `main.py` yet — anything that can reach the endpoint is treated as a trusted Chat event today.

## Tests

```bash
uv run pytest chat-service/tests
```

`test_smoke.py`, `test_rag_answer.py`, `test_dialog_prefill.py`, `test_structured_tests.py`, `test_text.py` — cover the RAG pipeline, dialog/ticket pre-fill flows, structured-request routing, and the Markdown-to-Chat-HTML conversion. No live GCP/Freshservice calls are made in tests.

## Known gaps

- Google Chat requests aren't signature-verified before processing.
- `rag_latency_check.py` is a manual benchmarking tool, not wired into CI or monitoring.
- The "AI-drafted ticket" path (`analyzeForTicket` / `buildSmartTicket`) and the structured-request path (`openStructuredDialog`) use hardcoded test values for some fields (`_test_values_for` in `main.py`) pending a real field-collection step.
