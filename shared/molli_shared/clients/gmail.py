"""Gmail API client for sending escalation notification emails.

Uses domain-wide delegation (DWD) via the Cloud Run service account's
built-in ADC credentials + IAM JWT signing — no service account key file
required. This works even when iam.disableServiceAccountKeyCreation is
enforced at the org level.

One-time GCP setup:
  1. Enable the Gmail API on the GCP project.
  2. Enable domain-wide delegation on the Cloud Run SA (GCP Console →
     IAM & Admin → Service Accounts → [SA] → Advanced settings → DWD).
  3. In Google Admin Console → Security → API controls → Domain-wide
     delegation, add the SA client ID with scope:
       https://www.googleapis.com/auth/gmail.send
  4. Grant the SA permission to sign JWTs for itself:
       gcloud iam service-accounts add-iam-policy-binding SA_EMAIL \\
         --member="serviceAccount:SA_EMAIL" \\
         --role="roles/iam.serviceAccountTokenCreator"

The send_email() method is synchronous — the Gmail API client (googleapiclient)
is not async. Call it via FastAPI BackgroundTasks so it runs in a thread pool
and never blocks the event loop.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any

import structlog

log = structlog.get_logger()

_GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


class GmailClient:
    """Sends email via the Gmail API using keyless DWD.

    Args:
        sender_email:         Workspace address to send as (e.g. molli.svc@preiss.com).
        service_account_email: Cloud Run SA email (e.g. 123-compute@developer.gserviceaccount.com).
    """

    def __init__(self, *, sender_email: str, service_account_email: str) -> None:
        self._sender_email = sender_email
        self._service_account_email = service_account_email
        self._service: Any = None  # lazy-loaded

    def _get_service(self) -> Any:
        if self._service is None:
            import google.auth
            import google.auth.transport.requests
            from google.auth import iam
            from google.oauth2 import service_account
            from googleapiclient.discovery import build  # type: ignore[import-untyped]

            # ADC resolves to the Cloud Run metadata server — no key file needed.
            source_creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/iam"]
            )
            http_request = google.auth.transport.requests.Request()
            source_creds.refresh(http_request)  # type: ignore[no-untyped-call]

            # Sign JWTs via IAM API (requires iam.serviceAccounts.signJwt on the SA).
            signer = iam.Signer(  # type: ignore[no-untyped-call]
                request=http_request,
                credentials=source_creds,
                service_account_email=self._service_account_email,
            )
            creds = service_account.Credentials(  # type: ignore[no-untyped-call]
                signer=signer,
                service_account_email=self._service_account_email,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=[_GMAIL_SEND_SCOPE],
                subject=self._sender_email,  # DWD: act as this Workspace user
            )
            # cache_discovery=False avoids a filesystem write in Cloud Run.
            self._service = build(
                "gmail", "v1", credentials=creds, cache_discovery=False
            )
        return self._service

    def send_email(self, *, to: str, subject: str, body: str) -> None:
        """Send a plain-text email. Raises on failure — callers should catch."""
        msg = MIMEText(body)
        msg["to"] = to
        msg["from"] = self._sender_email
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self._get_service().users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
        log.info("gmail_sent", to=to, subject=subject)
