FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY sync-job/ ./sync-job/
COPY shared/ ./shared/

RUN uv sync --frozen --package sync-job --no-dev

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

WORKDIR /app/sync-job
CMD ["python", "-m", "sync_job.main"]
