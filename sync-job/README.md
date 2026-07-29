# sync-job

Nightly batch job that keeps Molli's knowledge index current: Document360 → chunk → embed → Vertex AI Vector Search. Deployed as a Cloud Run **job** (not a service — no HTTP server; Cloud Scheduler triggers a run to completion). See [`Dockerfile`](Dockerfile) at the repo root and `.github/workflows/deploy-sync-job.yml`. Depends on [`shared`](../shared/README.md).

> **Note on layout:** the real entrypoint is `sync_job/main.py` (`python -m sync_job.main`, per the Dockerfile `ENTRYPOINT`). `app/main.py` is an earlier scaffold stub left in place — it isn't invoked by anything and can be removed once nothing references it.

## Pipeline

Implemented in [`sync_job/main.py`](sync_job/main.py) (`run_sync`):

1. Read the watermark from Firestore (`sync_state/document360`, `last_synced_at`). No watermark → full sync.
2. `Document360Client.list_articles(modified_since=watermark)` — client-side filter (D360 has no server-side "modified since" query); D360 embeds article stubs in its category-tree response, so listing needs no pagination.
3. Fetch each changed article's full HTML body individually — one bad article (some D360 articles 429 on every attempt, likely oversized or broken server-side) can't crash the whole run. Failures are collected, logged, and retried on the next run via a separate Firestore-persisted retry list (independent of the watermark, since failed articles are older than the new watermark and wouldn't otherwise be picked up again).
4. Chunk each article's HTML by heading boundary (`sync_job/chunking.py`), targeting ~750 tokens/chunk (approximate char/4 counting, no tokenizer dependency) so each chunk stays topically coherent and citable.
5. Embed chunks with `text-embedding-004` (768-dim, `RETRIEVAL_DOCUMENT` task type), passing the article title alongside body text so short title-shaped queries still match.
6. Batch-upsert to Vertex AI Vector Search (100 datapoints/batch, paced with a sleep between batches to stay under the stream-update quota) and write chunk text to Firestore (`ChunkStore`) keyed by the same datapoint ID — Vector Search only stores the embedding + small metadata, not the text itself.
7. Advance the watermark to the run's **start** time (not end), so articles modified mid-run are safely picked up next cycle, and persist the updated failed-article list.

Datapoint IDs are `{article_id}::{ordinal}` — deterministic, so re-runs overwrite rather than duplicate (idempotent).

## Layout

```
app/main.py                 Unused scaffold stub (see note above) — not the real entrypoint
sync_job/
  main.py                   Real entrypoint and pipeline orchestrator (run_sync, main)
  chunking.py                HTML -> heading-aware text chunks
  watermark.py               Firestore-backed incremental sync state (watermark + failed-article retry list)
  embedding.py, index_store.py   Compatibility re-exports — real implementations live in
                              shared/molli_shared/retrieval/ (embedding.py, index_store.py) so
                              chat-service can reuse the same Embedder/VectorIndex for query-time embedding
  manual_ingest.py           Stopgap CLI: manually ingest a PDF not yet in Document360 into the
                              same Vector Search + Firestore stores the nightly job writes to
  query_test.py               Ad-hoc CLI to sanity-check retrieval against the live index
  rag_retrieval_check.py      Manual retrieval-quality check script (question/expected-article pairs)
  pdfs/                       Sample PDFs used with manual_ingest.py (benefits, FSA, recruiting docs)
```

## Running locally

```bash
uv sync --all-packages          # from repo root
cd sync-job

uv run python -m sync_job.main                    # incremental (uses Firestore watermark)
uv run python -m sync_job.main --skip-watermark    # full sync, no Firestore read/write (first run)
uv run python -m sync_job.main --limit 200         # first N articles only (testing)

uv run python -m sync_job.query_test "your question here"   # sanity-check retrieval
```

Needs `.env` with `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `VECTOR_INDEX_ID`, `VECTOR_INDEX_ENDPOINT`, `FRESHSERVICE_DOMAIN` (see `shared/molli_shared/config.py`), plus Application Default Credentials (`gcloud auth application-default login`). The Document360 API key comes from Secret Manager, not `.env`.

The deployed index ID (`molli_knowledge_stream`) and the Vector Search public endpoint domain are hardcoded as documented defaults at the top of `sync_job/main.py` — override via env if they change or when provisioning a new environment.

## Manual PDF ingest

For content that needs to be answerable before it exists in Document360:

```bash
uv run python -m sync_job.manual_ingest <path-to-pdf>
```

Writes to the same Vector Search index and Firestore chunk store as the nightly job, under a `pdf-manual::<slug>` article ID, so `chat-service` grounds and cites it exactly like a real D360 article.

## Tests

`sync-job/tests/` currently has no real test coverage — it's effectively unimplemented compared to `chat-service/tests/` and `shared/tests/`. This is the biggest test-coverage gap in the repo and a good first place to invest before further changes to the pipeline.

## Known gaps / follow-ups

- No tests for `run_sync`, chunking, or the watermark store.
- Retrieval quality is untuned — title-only chunks (`::0`) underperform; a re-ranking step or heading-prefixed body chunks could help.
- `remove_article`-style stale-chunk cleanup doesn't exist — if a re-synced article shrinks, old higher-ordinal chunks from the previous version linger in the index/Firestore.
- Persistently-failing D360 articles (429 on every attempt) are skipped and retried indefinitely; if the retry list only grows, that signals a genuinely broken article needing manual attention in Document360, not a transient rate-limit issue.
