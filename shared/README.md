# shared (`molli-shared`)

Shared Python package used by both `chat-service` and `sync-job`: API clients, the guardrail chain, retrieval/embedding, Firestore-backed stores, and Pydantic schemas. Neither service reimplements any of this — if it's business logic and more than one package needs it (or plausibly will), it belongs here.

## Layout

```
molli_shared/
  config.py                  Settings model — non-secret env vars + Secret Manager accessor
  clients/
    document360.py            Document360 v2 API client (list/get articles, incremental sync support)
    freshservice.py            Freshservice REST v2 client — retries on 429 (Retry-After) and 5xx, terminal on 4xx/401/403
    ticketing.py                TicketingProvider protocol — the abstraction chat-service depends on, not Freshservice directly
    gmail.py                    Gmail API client (domain-wide delegation) for escalation emails — implemented but not currently called from anywhere
  guardrails/
    base.py                     Guardrail protocol, Action enum (ALLOW/BLOCK/REDACT/ESCALATE), GuardrailVerdict
    chain.py                     run_chain() — runs all guardrails in priority order; scan_gemini_output() — output-side DLP pass
    mental_health.py             Distress/crisis detection -> ESCALATE to EAP referral
    osha.py                       Two-tier workplace safety: Tier 1 emergency -> ESCALATE, Tier 2 general -> ALLOW + mandatory referral
    fair_housing.py               FHA regex fast path -> BLOCK
    llm_classifier.py             FHA semantic fallback for phrasing the regex misses (Gemini, fail-open to ALLOW)
    fcra.py                       FCRA (background check / credit) guidance -> BLOCK
    hr_legal.py                   Harassment/discrimination/retaliation disclosures -> ESCALATE, HR-only routing
    data_priv.py / dlp.py         PII detection (Cloud DLP) on input and Gemini output; dlp.py wraps the DLP API, data_priv.py has the regex pre-filter + BLOCK/REDACT policy
    escalation.py                 3-tier flow: answer -> ticket offer (low confidence) -> human handoff (explicit request, repeated questions, frustration signals)
    eval_harness.py               Standalone script: runs guardrail-eval-prompts through the chain and reports pass rate
  retrieval/
    embedding.py                  Vertex AI text-embedding-004 wrapper (768-dim)
    index_store.py                 Vertex AI Vector Search upsert/query, datapoint id scheme {article_id}::{ordinal}
  chunk_store.py               Firestore store for chunk text, keyed by Vector Search datapoint id (collection `chunks`)
  conversation_store.py        Firestore per-session conversation memory; DLP-scrubs turns before storage and fails CLOSED on a DLP outage (stores a placeholder rather than risk raw PII)
  intent.py                    Department classifier (HR/IT/Ops/general) for retrieval scoping + ticket routing
  query_rewrite.py              Rewrites multi-turn follow-ups ("what about for Mac?") into standalone retrieval queries
  topic_detection.py            Detects when a new message is a different topic than recent history, for the reset-history prompt
  ticket_analysis.py            Conversation -> TicketAnalysis (summary, routing fields, follow-up questions) for AI-drafted tickets
  vertex_retry.py                Shared bounded-retry decorator for Vertex calls without their own timeout wrapper (RAG generation/embedding)
  schemas/
    article.py                  Document360 article models (PII fields like authors/created_by deliberately omitted)
    ticket.py                    Freshservice payload models (TicketCreatePayload, CreatedTicket) + TicketDraft (confidence-tagged fields for pre-fill UIs)
    factories.py                 Test/dev factories for building TicketDraft objects (make_draft, make_partial_draft, make_empty_draft)
```

## Design conventions worth knowing before changing this code

- **Every LLM-backed helper here fails open or fails safe on error/timeout** (`intent.py`, `query_rewrite.py`, `topic_detection.py`, `llm_classifier.py`, `ticket_analysis.py`): a classifier outage degrades behavior (unscoped retrieval, no rewrite, no reset prompt) rather than blocking or crashing the chat reply. They all follow the same shape: a named `_call_gemini()` (so tests can patch it directly), `asyncio.to_thread` + `asyncio.wait_for` timeout, broad `except Exception` fallback.
- **Cloud DLP fails open for scanning, closed for storage.** `dlp.py`/`data_priv.py` return unscanned text on a DLP outage so message *handling* doesn't stop (availability over blocking). `conversation_store.py` overrides that for *persistence*: if the scan was skipped, it stores a placeholder instead of ever writing unscanned text to Firestore.
- **`TicketingProvider` is a `Protocol`, not a base class.** `chat-service` only depends on `lookup_requester` and `create_ticket`. Adding methods to the protocol is effectively an interface change for any future non-Freshservice implementation — coordinate before doing it.
- **Guardrail chain order is priority order, not alphabetical or file order** — see `chain.py`'s `_GUARDRAIL_CHAIN` list and its module docstring for the documented priority (Mental Health > OSHA > FHA > HR/Legal > Data Privacy > Escalation).
- **Vector Search stores vectors + short metadata tokens only.** Chunk text always goes through `chunk_store.py`/Firestore, keyed by the same `{article_id}::{ordinal}` datapoint id used in the index, to keep index payloads small.

## Tests

```bash
uv run pytest shared/tests
```

Guardrail-specific tests live under `shared/tests/guardrails/` (one file per guardrail, plus `test_false_positives.py` for phrases that must NOT trigger). Client tests (`test_freshservice_client.py`, `test_document360.py`) mock all HTTP via `respx`/`pytest-httpx` — no test hits a live API. `test_conversation_memory.py`, `test_dlp.py`, `test_intent.py`, `test_ticket_schemas.py` round out the rest.

## Known gaps

- `clients/gmail.py` is fully implemented but not called from `chat-service` or `sync-job` — escalation notifications currently go out via the Chat incoming-webhook path in `chat-service/app/main.py`, not email.
- FCRA enforcement is split between `fcra.py` (regex) and the FHA/FCRA semantic classifier in `llm_classifier.py` rather than having a single dedicated chain entry — read both before changing FCRA behavior.
- `guardrails/eval_harness.py` and `intent_eval.py` are manual evaluation scripts (produce `eval_results.json` at the repo root), not part of CI.
