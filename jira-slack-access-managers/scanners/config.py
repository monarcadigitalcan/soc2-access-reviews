"""
Configuration module — pulls credentials from GCP Secret Manager
and provides GCS upload utilities.

For local development, falls back to environment variables.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Auto-load .env file (so you don't need to export vars every session)
# --------------------------------------------------------------------------- #
def _load_env_file():
    """Load .env file from project root if it exists."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        logger.info(f"Loading environment from {env_path}")
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Don't override existing env vars
                    if key not in os.environ:
                        os.environ[key] = value


_load_env_file()

# --------------------------------------------------------------------------- #
#  Environment / defaults
# --------------------------------------------------------------------------- #
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "")
JIRA_SITE_URL = os.getenv("JIRA_SITE_URL", "")  # e.g. https://acme.atlassian.net

# Secret Manager key names
SECRET_JIRA_TOKEN = "jira-access-review-token"
SECRET_JIRA_EMAIL = "jira-admin-email"
SECRET_SLACK_TOKEN = "slack-access-review-bot-token"

# Optional: offboarding DB connection (Phase 2)
SECRET_OFFBOARDING_DB_URL = "offboarding-db-url"


# --------------------------------------------------------------------------- #
#  Secret Manager
# --------------------------------------------------------------------------- #
def get_secret(secret_id: str, project_id: str = None) -> str:
    """
    Retrieve a secret from GCP Secret Manager.
    Falls back to environment variables for local dev.
    """
    # Local dev fallback: check env vars first
    env_key = secret_id.upper().replace("-", "_")
    env_val = os.getenv(env_key)
    if env_val:
        logger.info(f"Using env var {env_key} (local dev mode)")
        return env_val

    project = project_id or GCP_PROJECT_ID
    if not project:
        raise RuntimeError(f"Cannot fetch secret '{secret_id}': GCP_PROJECT_ID not set and no env var fallback found.")

    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch secret '{secret_id}': {e}") from e


# --------------------------------------------------------------------------- #
#  GCS Upload
# --------------------------------------------------------------------------- #
def upload_csv_to_gcs(
    local_path: str,
    platform: str,
    bucket_name: str = None,
    prefix: str = None,
) -> str:
    """
    Upload a CSV file to GCS with date-stamped path.
    Returns the GCS URI (gs://...).

    Path format: gs://<bucket>/<prefix>/<date>/<platform>_access_review.csv
    """
    bucket = bucket_name or GCS_BUCKET_NAME
    if not bucket:
        raise RuntimeError("GCS_BUCKET_NAME not set")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prefix = prefix or "access-reviews"
    blob_name = f"{prefix}/{date_str}/{platform}_access_review.csv"

    try:
        from google.cloud import storage

        client = storage.Client()
        bucket_obj = client.bucket(bucket)
        blob = bucket_obj.blob(blob_name)
        blob.upload_from_filename(local_path)
        gcs_uri = f"gs://{bucket}/{blob_name}"
        logger.info(f"Uploaded {local_path} -> {gcs_uri}")
        return gcs_uri
    except Exception as e:
        raise RuntimeError(f"Failed to upload to GCS: {e}") from e


# --------------------------------------------------------------------------- #
#  Offboarding DB (Phase 2 — stub)
# --------------------------------------------------------------------------- #
def get_departed_employees(quarter: str = None) -> list[str]:
    """
    Query the offboarding database for departed employee emails.
    Returns a list of email addresses.

    Phase 2: will connect to the offboarding app's database.
    Currently returns an empty list.
    """
    # TODO Phase 2: implement DB query
    # db_url = get_secret(SECRET_OFFBOARDING_DB_URL)
    # query departed_employees table for current + previous quarter
    logger.info("Offboarding DB integration not yet active (Phase 2)")
    return []
