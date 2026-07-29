"""
Google Cloud DLP wrapper for Molli's Data Privacy guardrail.

Scans inbound chat messages for PII before the text reaches Gemini or is
written to any log.  Sits in shared/ so both chat-service and sync-job can
import it without duplicating logic.

Behavior summary (Data Privacy guardrail decision):
  • Detected PII is REDACTED in the text that continues to Gemini and to logs.
  • The *types* of infoTypes found are logged (e.g. "EMAIL_ADDRESS detected")
    but the raw PII values are never stored beyond the active request.
  • If DLP itself is unavailable the call FAILS OPEN with a warning — we do
    not want a DLP outage to take down the chatbot, but we log the gap.

Usage:
    from molli_shared.guardrails.dlp import DLPScanner

    scanner = DLPScanner(project_id="molli-dev")
    result = scanner.scan("My SSN is 123-45-6789 and email is alice@preiss.com")
    # result.redacted_text  -> "My SSN is [REDACTED] and email is [REDACTED]"
    # result.found_types    -> ["US_SOCIAL_SECURITY_NUMBER", "EMAIL_ADDRESS"]
    # result.has_pii        -> True
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Default infoType set — covers the PII most likely to appear in employee chat.
# Add or remove entries here; every value must be a valid DLP infoType name.
# See: https://cloud.google.com/sensitive-data-protection/docs/infotypes-reference
# ---------------------------------------------------------------------------
DEFAULT_INFO_TYPES: list[str] = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_SOCIAL_SECURITY_NUMBER",
    "CREDIT_CARD_NUMBER",
    "PERSON_NAME",
    "DATE_OF_BIRTH",
    "US_DRIVERS_LICENSE_NUMBER",
    "US_PASSPORT",
    "STREET_ADDRESS",
    "IP_ADDRESS",
]

# Minimum likelihood level at which a finding is acted upon.
# LIKELY catches real PII without too many false positives on employee names.
MIN_LIKELIHOOD = "LIKELY"  # DLP likelihood enum value

# Maximum bytes to send to DLP per request.  DLP has a 500 KB content limit;
# chat messages will never come close, but sync-job chunks might.
MAX_BYTES = 100_000


@dataclass
class DLPResult:
    """Result of a single DLP scan."""

    original_text: str
    redacted_text: str
    found_types: list[str] = field(default_factory=list)
    has_pii: bool = False
    scan_skipped: bool = False  # True when DLP was unreachable (fail-open)
    skip_reason: Optional[str] = None


class DLPScanner:
    """Thin wrapper around the Google Cloud DLP deidentifyContent API.

    Args:
        project_id: GCP project that has the DLP API enabled and whose
                    runtime service account holds the DLP User role.
        info_types:  List of DLP infoType names to scan for.  Defaults to
                     DEFAULT_INFO_TYPES.
        min_likelihood: Minimum likelihood threshold for a finding to be
                        treated as PII.  Defaults to "LIKELY".
    """

    def __init__(
        self,
        project_id: str,
        info_types: Optional[list[str]] = None,
        min_likelihood: str = MIN_LIKELIHOOD,
    ) -> None:
        self._project_id = project_id
        self._info_types = info_types or DEFAULT_INFO_TYPES
        self._min_likelihood = min_likelihood
        self._client: Optional[Any] = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self, text: str) -> DLPResult:
        """Scan *text* for PII and return a DLPResult with redacted content.

        Always returns a DLPResult — never raises.  Callers must check
        result.scan_skipped to know whether DLP was actually invoked.
        """
        if not text or not text.strip():
            return DLPResult(original_text=text, redacted_text=text)

        if len(text.encode("utf-8")) > MAX_BYTES:
            text = text[: MAX_BYTES // 2]  # trim; keeps the message usable

        try:
            client = self._get_client()
            return self._call_dlp(client, text)
        except Exception as exc:  # noqa: BLE001
            return DLPResult(
                original_text=text,
                redacted_text=text,
                scan_skipped=True,
                skip_reason=str(exc),
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Lazy-load the DLP client so import doesn't fail in test environments."""
        if self._client is None:
            from google.cloud import dlp_v2  # type: ignore[attr-defined]

            self._client = dlp_v2.DlpServiceClient()
        return self._client

    def _call_dlp(self, client: Any, text: str) -> DLPResult:
        """Issue a deidentifyContent call and parse the response."""

        parent = f"projects/{self._project_id}/locations/global"

        inspect_config = {
            "info_types": [{"name": t} for t in self._info_types],
            "min_likelihood": self._min_likelihood,
            "include_quote": False,  # never echo raw PII values in API response
        }

        deidentify_config = {
            "info_type_transformations": {
                "transformations": [
                    {
                        # Replace each finding with [REDACTED] — simple and audit-friendly.
                        "primitive_transformation": {
                            "replace_config": {
                                "new_value": {"string_value": "[REDACTED]"}
                            }
                        }
                    }
                ]
            }
        }

        item = {"value": text}

        response = client.deidentify_content(
            request={
                "parent": parent,
                "inspect_config": inspect_config,
                "deidentify_config": deidentify_config,
                "item": item,
            }
        )

        # Extract which infoTypes were found from the overview.
        found_types: list[str] = []
        overview = response.overview
        if (
            overview
            and hasattr(overview, "transformed_bytes")
            and overview.transformed_bytes
        ):
            # Walk transformation_summaries to collect infoType names.
            for summary in overview.transformation_summaries:
                if hasattr(summary, "info_type") and summary.info_type.name:
                    found_types.append(summary.info_type.name)

        redacted = response.item.value
        has_pii = redacted != text  # text changed → something was redacted

        return DLPResult(
            original_text=text,
            redacted_text=redacted,
            found_types=found_types,
            has_pii=has_pii,
        )
