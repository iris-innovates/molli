"""Document360 API client.

Enumerates the content tree, lists article stubs, fetches full article
content, and supports incremental sync via a stored modified-at watermark.

API docs: https://apidocs.document360.io/

Design notes (confirmed against the live Preiss Central instance)
-------------------------------------------------------------------------------
- Auth is a custom header: ``api_token: <key>`` (NOT ``Authorization: Bearer``).
- Base URL is region-specific. Preiss Central is on the US region:
  ``https://apihub.us.document360.io/v2``. This is configurable.
- There is NO server-side "modified since" filter. Incremental sync is
  client-side: walk the tree, compare each stub's ``modified_at`` against a
  stored watermark, and fetch full content only for the ones that changed.
- Articles are organised under a project version. Resolve a project version id
  first, then fetch its category tree. The category tree EMBEDS article stubs
  (id, title, modified_at, status, hidden, ...) at every level via the
  ``articles`` array, and nests via ``child_categories``. So the entire content
  inventory comes from a single ``/ProjectVersions/{id}/categories`` call — no
  per-category article listing, no pagination needed for enumeration.
- Full article content (the HTML body) comes from the single-article endpoint,
  which requires a language code: ``/Articles/{id}/{langCode}``.
- Responses are wrapped in an envelope: ``{"data": ..., "success": bool, ...}``.
  Article content comes back as HTML in the ``html_content`` field.

Indexing filter: only ``status == 3`` (published) AND ``not hidden`` articles
should be indexed. ``security_visibility`` semantics are still unconfirmed and
are NOT filtered on.

Typical sync usage::

    client = Document360Client.from_settings()
    async with client:
        changed = await client.list_articles(modified_since=watermark)
        full = await client.get_articles(
            [(a.id, a.language_code) for a in changed]
        )
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from molli_shared.config import get_secret, get_settings
from molli_shared.schemas.article import (
    Article,
    ArticleStub,
    Category,
    ProjectVersion,
)

# Region-specific. Preiss Central is US. Override via settings if this changes.
DEFAULT_BASE_URL = "https://apihub.us.document360.io/v2"

# Conservative concurrency cap for get_article fan-out during a nightly sync,
# to stay well under the rate limit.
_DEFAULT_CONCURRENCY = 4


class _RateLimiter:
    """Async token-bucket limiter that smooths request bursts.

    D360's documented limit is 1500 req/min/IP, but it also appears to enforce a
    short sliding-window sub-limit: a burst of concurrent requests can trip a 429
    even while the per-minute average sits far below 1500. This limiter caps the
    RATE at which requests may START, which is what prevents the bursts.

    Default 20 req/sec = 1200 req/min, leaving headroom under the 1500 ceiling.
    """

    def __init__(self, rate_per_sec: float = 12.0, burst: int = 5) -> None:
        self._rate = rate_per_sec
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._updated
            self._updated = now
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


class Document360Error(RuntimeError):
    """Raised when the API returns a non-success envelope or HTTP error."""


class Document360Client:
    """Async client for the Document360 v2 API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        max_retries: int = 5,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._max_retries = max_retries
        self._limiter = _RateLimiter()
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "api_token": api_key,
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    @classmethod
    def from_settings(
        cls,
        base_url: str = DEFAULT_BASE_URL,
        **kwargs: Any,
    ) -> Document360Client:
        """Build a client with the API key pulled from Secret Manager via the
        shared config. Use this in the sync job / Cloud Run; tests construct the
        client directly with a fake key instead."""
        settings = get_settings()
        api_key = get_secret(settings.document360_secret_name, settings.gcp_project_id)
        return cls(api_key, base_url=base_url, **kwargs)

    # -- context management -------------------------------------------------

    async def __aenter__(self) -> Document360Client:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- low-level request with retry/backoff -------------------------------

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a path, honour Retry-After / backoff, and unwrap the envelope.

        Returns the contents of the ``data`` field. Raises Document360Error on
        a non-success envelope or after exhausting retries.
        """
        backoff = 1.0
        last_exc: Exception | None = None

        for _attempt in range(self._max_retries):
            await self._limiter.acquire()
            try:
                response = await self._client.get(path, params=params or None)
            except httpx.TransportError as exc:  # network blip
                last_exc = exc
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0) * (0.5 + random.random())
                continue

            if response.status_code == 429:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                await asyncio.sleep(retry_after if retry_after is not None else backoff)
                backoff = min(backoff * 2, 60.0) * (0.5 + random.random())
                continue

            if response.status_code >= 500:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0) * (0.5 + random.random())
                continue

            if response.status_code == 401:
                raise Document360Error(
                    "401 Unauthorized — check the api_token header and key. "
                    "The D360 v2 API expects a custom 'api_token' header, not a "
                    "Bearer token."
                )

            response.raise_for_status()
            payload = response.json()
            return _unwrap(payload)

        raise Document360Error(
            f"GET {path} failed after {self._max_retries} retries"
        ) from last_exc

    # -- public API ---------------------------------------------------------

    async def get_project_versions(self) -> list[ProjectVersion]:
        """Return the project versions. Article listing is scoped to a version."""
        data = await self._get("/ProjectVersions")
        if not isinstance(data, list):
            return []
        return [ProjectVersion.model_validate(v) for v in data]

    async def _resolve_version(self, version_id: str | None) -> ProjectVersion:
        """Resolve the project version to sync.

        Defaults to the main version if present, else the first one. If Preiss
        Central grows multiple versions (e.g. public vs internal), pass an
        explicit ``version_id`` rather than relying on this.
        """
        versions = await self.get_project_versions()
        if not versions:
            raise Document360Error("No project versions returned")
        if version_id is not None:
            for v in versions:
                if v.id == version_id:
                    return v
            raise Document360Error(f"Project version {version_id!r} not found")
        for v in versions:
            if v.is_main_version:
                return v
        return versions[0]

    async def get_categories(self, version_id: str) -> list[Category]:
        """Return the (nested) category tree for a project version. Each node
        embeds its article stubs and may nest via ``child_categories``."""
        data = await self._get(f"/ProjectVersions/{version_id}/categories")
        if not isinstance(data, list):
            return []
        return [Category.model_validate(c) for c in data]

    async def list_articles(
        self,
        modified_since: datetime | None = None,
        *,
        version_id: str | None = None,
        lang_code: str | None = None,
        indexable_only: bool = True,
    ) -> list[ArticleStub]:
        """List article stubs across the whole content tree for a version.

        Returns lightweight metadata per article (id, title, modified_at,
        status, hidden, category id, ...) — NOT the full body. Call
        ``get_article`` for content.

        Enumeration is a single category-tree fetch followed by an in-memory
        recursive walk; the tree embeds every article stub. No pagination.

        ``indexable_only`` keeps only published, non-hidden articles
        (``status == 3 and not hidden``).

        ``modified_since`` is applied CLIENT-SIDE (the API has no server-side
        filter): stubs whose ``modified_at`` is at or before the watermark are
        dropped, so the *fetch* step stays incremental even though the *list*
        step is a full walk.
        """
        version = await self._resolve_version(version_id)
        categories = await self.get_categories(version.id)

        stubs: list[ArticleStub] = []
        for category in categories:
            stubs.extend(category.iter_articles())

        if indexable_only:
            stubs = [s for s in stubs if s.is_indexable]

        if modified_since is not None:
            cutoff = _as_utc(modified_since)
            stubs = [s for s in stubs if _as_utc(s.modified_at) > cutoff]

        return stubs

    async def get_article(self, article_id: str, lang_code: str = "en") -> Article:
        """Fetch a single article's full content (HTML body + metadata).

        The endpoint requires a language code path segment:
        ``/Articles/{id}/{langCode}``.
        """
        data = await self._get(f"/Articles/{article_id}/{lang_code}")
        if not isinstance(data, dict):
            raise Document360Error(
                f"Unexpected payload for article {article_id!r}: {type(data)}"
            )
        return Article.model_validate(data)

    async def get_articles(
        self,
        articles: list[tuple[str, str]],
        *,
        concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> list[Article]:
        """Fetch many articles with a bounded concurrency cap.

        ``articles`` is a list of ``(article_id, lang_code)`` tuples — typically
        ``[(s.id, s.language_code) for s in changed_stubs]``.
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def _one(aid: str, lang: str) -> Article:
            async with semaphore:
                return await self.get_article(aid, lang)

        return await asyncio.gather(*(_one(aid, lang) for aid, lang in articles))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unwrap(payload: Any) -> Any:
    """Unwrap the D360 ``{"data": ..., "success": ...}`` envelope."""
    if isinstance(payload, dict) and "data" in payload and "success" in payload:
        if not payload.get("success", True):
            raise Document360Error(
                f"API returned success=false: {payload.get('errors')}"
            )
        return payload["data"]
    return payload


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After may be seconds or an HTTP date. Return seconds to wait."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(value)
        delta = (when - datetime.now(UTC)).total_seconds()
        return max(delta, 0.0)
    except (TypeError, ValueError):
        return None
