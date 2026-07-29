# Molli

Molli is Preiss Companies' AI employee assistant, delivered as a Google Chat app. Employees ask HR/IT/Ops questions; Molli runs the message through a compliance guardrail chain, retrieves grounded answers from Preiss Central (Document360) via RAG, and replies inline in Chat with citations. When it can't answer, it offers a pre-filled Freshservice ticket.

## Repo layout

This is a `uv` workspace with three Python packages plus infra/CI. Each package has its own README with setup and implementation detail:

| Path | What | README |
|---|---|---|
| [`chat-service/`](chat-service/) | FastAPI app — Cloud Run service handling Google Chat events, guardrails, RAG, ticketing | [chat-service/README.md](chat-service/README.md) |
| [`sync-job/`](sync-job/) | Cloud Run job — nightly Document360 → Vector Search sync | [sync-job/README.md](sync-job/README.md) |
| [`shared/`](shared/) | `molli-shared` package — clients, guardrails, schemas, retrieval used by both services | [shared/README.md](shared/README.md) |
| `infra/terraform/` | Terraform skeleton for GCP resources (provider + variables only — see note below) | — |
| `scripts/` | One-off exploration/spike scripts (Freshservice, Document360, Gemini function calling, vector search) — not part of the running app | — |
| `.github/workflows/` | CI (lint, type check, test, coverage gate) and Cloud Run deploy workflows | — |

## Architecture

```
Google Chat  --SSO-->  chat-service (Cloud Run)
                            |
              +-------------+-------------+
              |             |             |
        guardrail       RAG pipeline   Freshservice
          chain        (Vector Search    (tickets)
       (7 checks)      + Firestore text)
              |             ^
              |             | nightly upsert
              |             |
        Firestore      sync-job (Cloud Run job)
      (conversation           |
        memory)         Document360 (Preiss Central)
```

- **chat-service** — handles Google Chat `MESSAGE`/`CARD_CLICKED` events. Every inbound message runs through the guardrail chain first; only messages that clear it reach Gemini. See its README for the full request flow.
- **sync-job** — runs on a schedule (Cloud Scheduler → Cloud Run job), not per-request. Pulls changed Document360 articles, chunks, embeds, and upserts to Vertex AI Vector Search, with chunk text mirrored to Firestore.
- **shared (`molli-shared`)** — the only place API clients, guardrail logic, and Pydantic schemas are implemented. Both services depend on it; neither reimplements it.

## Guardrails

Every inbound message runs through this chain, in order, before Gemini is called. Any `BLOCK` or `ESCALATE` short-circuits the rest of the chain:

| Order | Guardrail | Action |
|---|---|---|
| 1 | Mental Health | ESCALATE → EAP referral |
| 2 | OSHA / Workplace Safety (Tier 1 emergency) | ESCALATE |
| 3 | Fair Housing (FHA) — regex fast path | BLOCK |
| 4 | FHA — LLM semantic fallback (ambiguous phrasing only) | BLOCK |
| 5 | HR / Legal risk (harassment, discrimination, retaliation) | ESCALATE → HR-only intake |
| 6 | Data Privacy (Cloud DLP input scan) | REDACT or BLOCK |
| 7 | Escalation (3-tier: answer → ticket offer → human handoff) | varies |

FCRA is enforced inside the Data Privacy/FHA classifier path rather than as a standalone chain entry — see [`shared/README.md`](shared/README.md) for the guardrail-by-guardrail detail. Gemini output is scanned again on the way out (Data Privacy Mode B) before it reaches the user.

## Ticketing: Freshservice → Autotask migration

Preiss plans to move off Freshservice onto Autotask at some point in the future. The ticketing integration is deliberately built so that swap doesn't touch chat-service's core logic:

- **`TicketingProvider` protocol** (`shared/molli_shared/clients/ticketing.py`) is the only interface `chat-service` depends on — just `lookup_requester(email)` and `create_ticket(payload)`, plus a provider-agnostic `TicketingError` exception hierarchy (`TicketingAuthError`, `TicketingValidationError`, `TicketingRateLimitError`) that callers already handle generically.
- **`FreshserviceClient`** (`shared/molli_shared/clients/freshservice.py`) is today's only implementation of that protocol.
- The **only place chat-service constructs a concrete client** is one line in `lifespan()` in `chat-service/app/main.py`:
  ```python
  app.state.ticketing = FreshserviceClient(
      base_url=settings.freshservice_base_url,
      api_key=settings.freshservice_api_key,
  )
  ```
  Every dialog handler, ticket mapper, and ticket-analysis adapter under `chat-service/app/cards/` only calls `request.app.state.ticketing.create_ticket(...)` / `.lookup_requester(...)` on whatever provider is installed there — none of them import Freshservice directly.

**To add Autotask:**
1. Write `shared/molli_shared/clients/autotask.py` implementing `TicketingProvider` (the same two async methods, raising the same `TicketingError` subclasses on failure).
2. Swap the import and constructor call in `main.py`'s `lifespan()` to the new client.
3. Everything else — card builders, dialog flow, guardrail-triggered escalations, structured-request routing — is unchanged, since none of it touches Freshservice directly.

**One thing that isn't free:** `TicketCreatePayload` / `MolliCustomFields` (`shared/molli_shared/schemas/ticket.py`) are modeled to match Freshservice's field names and enums exactly — the API rejects unknown keys, so this is a Freshservice-shaped schema, not a neutral one. If Autotask's ticket model differs meaningfully, the new client will need to translate from `TicketCreatePayload` into Autotask's request shape internally. The protocol guarantees the swap is a one-file *client* change — it doesn't guarantee zero schema work if the two platforms model tickets very differently.

## Local setup

Prerequisites: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), `gcloud` CLI, and access to the target GCP project (Application Default Credentials).

```bash
git clone <repo-url>
cd molli
uv sync --all-packages              # installs all three packages + dev deps
gcloud auth application-default login
cp .env.example .env                 # fill in non-secret config; secrets come from Secret Manager
```

Run a service locally — see the package READMEs for exact commands and required env vars:

```bash
cd chat-service && uv run uvicorn app.main:app --reload --port 8080
cd sync-job && uv run python -m sync_job.main --skip-watermark
```

## Quality gates

```bash
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run mypy chat-service sync-job shared
uv run pytest --cov --cov-report=term
```

CI (`.github/workflows/ci.yml`) runs all four on every PR and push to `main`, plus a coverage gate (currently 30% minimum, see `[tool.coverage.run]` in `pyproject.toml` for scope). Two separate workflows (`deploy-chat-service.yml`, `deploy-sync-job.yml`) build and deploy each service to Cloud Run on push to `main`, authenticating via Workload Identity Federation (no service-account keys).
