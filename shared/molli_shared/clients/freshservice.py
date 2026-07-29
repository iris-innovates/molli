"""Freshservice implementation of the TicketingProvider protocol.

- Auth: HTTP Basic with API key as username, "X" as password.
- Base URL: per-tenant Freshservice hostname (NOT the support portal domain
  — that's UI-only). For Preiss, this is
  ``https://tpco-org.freshservice.com/api/v2``.
- Required ticket fields confirmed from real responses: ``email``,
  ``group_id``, plus custom fields ``original_system``,
  ``original_more_detail``, ``msf_affected_location``.
- Source enum 4 = Chat (Molli's universal source).

Retries: honors ``Retry-After`` on 429s, exponential backoff with jitter on
5xx, max 3 attempts. 4xx errors other than 429 are terminal — typically a
validation problem the chat-service can surface immediately.

Tests live in ``shared/tests/test_freshservice_client.py`` and mock all
HTTP. No tests touch the live API. The Postman collection in
``postman/`` is the manual integration-test surface.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from molli_shared.clients.ticketing import (
    TicketingAuthError,
    TicketingError,
    TicketingRateLimitError,
    TicketingValidationError,
)
from molli_shared.schemas.ticket import (
    CreatedTicket,
    RequesterRecord,
    TicketCreatePayload,
)


class FreshserviceClient:
    """Concrete ``TicketingProvider`` implementation.

    Construction is cheap; reuse the same instance across requests in the
    chat-service. Always call ``aclose()`` (or use as an async context
    manager) before process exit so the underlying httpx client cleans up.

    For testing, pass a custom ``http_client`` to inject mocked transport.
    """

    DEFAULT_TIMEOUT = 30.0
    DEFAULT_MAX_RETRIES = 3
    MAX_BACKOFF_SECONDS = 30.0

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries

        if http_client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                auth=httpx.BasicAuth(api_key, "X"),
                timeout=timeout,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            self._owns_client = True
        else:
            self._client = http_client
            self._owns_client = False

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> FreshserviceClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ API

    async def lookup_requester(self, email: str) -> RequesterRecord | None:
        """Look up a requester by email.

        Returns ``None`` on no match (which Freshservice signals with an
        empty ``requesters`` array, not a 404). Raises on auth or transport
        failures.
        """
        response = await self._request("GET", "/requesters", params={"email": email})
        data = response.json()
        requesters = data.get("requesters", []) if isinstance(data, dict) else []
        if not requesters:
            return None
        return RequesterRecord.model_validate(requesters[0])

    async def create_ticket(self, payload: TicketCreatePayload) -> CreatedTicket:
        """Create a ticket from a strict payload.

        The payload's ``MolliCustomFields`` are serialized at the nested
        ``custom_fields`` key Freshservice expects. ``exclude_none=True``
        strips optional fields the caller didn't set, so Freshservice
        doesn't reject ``null`` values for fields it expects to be omitted.
        """
        body = payload.model_dump(exclude_none=True)
        response = await self._request("POST", "/tickets", json=body)
        data = response.json()
        # Freshservice wraps single-ticket responses in {"ticket": {...}}
        ticket = data.get("ticket", data) if isinstance(data, dict) else data
        return CreatedTicket.model_validate(ticket)

    # -------------------------------------------------------------- Internal

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Issue an HTTP request with retry logic.

        Retries on 5xx and 429 (honoring ``Retry-After``). Terminal on auth
        errors (401/403) and other 4xx. Raises a ``TicketingError`` subclass
        on terminal failure.
        """
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise TicketingError(
                    f"Network error after {self._max_retries + 1} attempts: {e}"
                ) from e

            if response.is_success:
                return response

            status = response.status_code
            body_preview = response.text[:500] if response.text else ""

            # Auth — terminal, no retry
            if status in (401, 403):
                raise TicketingAuthError(
                    f"Freshservice rejected credentials ({status}): {body_preview}",
                    status_code=status,
                    response_body=response.text,
                )

            # Rate limit — retry with Retry-After honored
            if status == 429:
                if attempt < self._max_retries:
                    wait = self._wait_for_retry_after(response, attempt)
                    await asyncio.sleep(wait)
                    continue
                raise TicketingRateLimitError(
                    f"Freshservice rate-limited; gave up after "
                    f"{self._max_retries + 1} attempts",
                    status_code=429,
                    response_body=response.text,
                )

            # Other 4xx — validation, terminal
            if 400 <= status < 500:
                raise TicketingValidationError(
                    f"Freshservice validation failure ({status}): {body_preview}",
                    status_code=status,
                    response_body=response.text,
                )

            # 5xx — retry with backoff
            if status >= 500:
                if attempt < self._max_retries:
                    wait = self._backoff(attempt)
                    await asyncio.sleep(wait)
                    continue
                raise TicketingError(
                    f"Freshservice server error ({status}) after retries: "
                    f"{body_preview}",
                    status_code=status,
                    response_body=response.text,
                )

        # Unreachable in practice — every branch above either returns or raises.
        raise TicketingError(  # pragma: no cover
            f"Unreachable retry-loop state; last_exc={last_exc!r}"
        )

    @classmethod
    def _backoff(cls, attempt: int) -> float:
        """Exponential backoff with jitter, capped at MAX_BACKOFF_SECONDS.

        attempt 0 -> ~1-1.5s
        attempt 1 -> ~2-2.5s
        attempt 2 -> ~4-4.5s
        """
        base = 2**attempt
        jitter = random.uniform(0, 0.5)
        return float(min(base + jitter, cls.MAX_BACKOFF_SECONDS))

    @classmethod
    def _wait_for_retry_after(cls, response: httpx.Response, attempt: int) -> float:
        """Parse the Retry-After header if present, otherwise fall back to
        exponential backoff. Freshservice typically returns seconds as an
        integer; we tolerate floats and ignore HTTP-date format (rare in
        practice for APIs)."""
        raw = response.headers.get("Retry-After")
        if not raw:
            return cls._backoff(attempt)
        try:
            return min(float(raw), cls.MAX_BACKOFF_SECONDS)
        except ValueError:
            return cls._backoff(attempt)
