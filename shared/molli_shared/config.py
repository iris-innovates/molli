"""Config loader.

Non-secret config from env vars; secrets from GCP Secret Manager.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from google.cloud import secretmanager
from pydantic import BaseModel


class Settings(BaseModel):
    gcp_project_id: str
    gcp_project_number: str
    gcp_region: str = "us-central1"
    environment: str = "dev"  # dev or prod
    document360_secret_name: str = "document360-api-key"
    freshservice_api_secret_name: str = "freshservice-api-key"
    freshservice_domain: str  # e.g. "tpco-org" — see freshservice_base_url
    vector_index_id: str | None = None
    vector_index_endpoint: str | None = None
    firestore_database: str = "(default)"
    # Google Chat HTTP endpoint — used as the expected JWT audience.
    # Set to the full Cloud Run service URL, e.g.
    # https://molli-chat-service-719635778769.us-central1.run.app
    chat_service_url: str | None = None

    # Gemini / Vertex AI (chat-service generative Q&A)
    use_gemini: bool = True
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.4
    freshservice_api_key: str  # required — the actual key, from Secret Manager
    freshservice_dry_run: bool = (
        False  # safe default; flip to False to create real tickets
    )

    # Escalation webhook — Google Chat incoming webhook URL.
    # When set, HR/OSHA/HR_LEGAL escalations POST a notification to this space.
    hr_escalation_webhook_url: str | None = None

    @property
    def freshservice_base_url(self) -> str:
        """Full base URL for Freshservice API.

        Constructed from the per-tenant domain. The custom support portal
        domain (support.preisscentral.com) is UI-only and does NOT serve the
        API — confirmed during the Postman spike. Always use the underlying
        *.freshservice.com hostname.
        """
        return f"https://{self.freshservice_domain}.freshservice.com/api/v2"


@lru_cache
def get_settings() -> Settings:
    load_dotenv()  # only reads .env on first call, so safe to call multiple times
    return Settings(
        gcp_project_id=os.environ["GCP_PROJECT_ID"],
        gcp_project_number=os.environ["GCP_PROJECT_NUMBER"],
        gcp_region=os.environ.get("GCP_REGION", "us-central1"),
        environment=os.environ.get("ENVIRONMENT", "dev"),
        vector_index_id=os.environ.get("VECTOR_INDEX_ID"),
        freshservice_domain=os.environ.get("FRESHSERVICE_DOMAIN", "tpco"),
        vector_index_endpoint=os.environ.get("VECTOR_INDEX_ENDPOINT"),
        chat_service_url=os.environ.get("CHAT_SERVICE_URL"),
        use_gemini=os.environ.get("MOLLI_USE_GEMINI", "true").lower() != "false",
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_temperature=float(os.environ.get("GEMINI_TEMPERATURE", "0.4")),
        freshservice_dry_run=os.environ.get("FRESHSERVICE_DRY_RUN", "false").lower()
        != "false",
        freshservice_api_key=os.environ["FRESHSERVICE_API_KEY"],
        hr_escalation_webhook_url=os.environ.get("HR_ESCALATION_WEBHOOK_URL"),
    )


def get_secret(secret_name: str, project_id: str, version: str = "latest") -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_name}/versions/{version}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")
