"""
Cloud Function HTTP entry point (Phase 2).

Exposes the same scan logic as cli.py but triggered via HTTP.
Intended to be called from the secure web frontend.

Deployment:
    gcloud functions deploy access-review-scan \
        --runtime python312 \
        --trigger-http \
        --entry-point scan \
        --set-env-vars GCP_PROJECT_ID=<project>,GCS_BUCKET_NAME=<bucket>,JIRA_SITE_URL=<url> \
        --service-account <sa>@<project>.iam.gserviceaccount.com

Request body (JSON):
    {
        "platforms": ["jira", "slack"],  // or just one
        "upload": true                   // upload to GCS (default: true)
    }

Response (JSON):
    {
        "status": "complete",
        "results": {
            "jira": {"status": "ok", "gcs_uri": "gs://...", "rows": 150},
            "slack": {"status": "ok", "gcs_uri": "gs://...", "rows": 320}
        }
    }
"""

import os
import json
import tempfile
import logging
import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("access-review-cf")

# Add parent dir to path so scanners module is importable
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@functions_framework.http
def scan(request):
    """HTTP Cloud Function entry point."""
    # Parse request
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}

    platforms = body.get("platforms", ["jira", "slack"])
    do_upload = body.get("upload", True)

    results = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        if "jira" in platforms:
            results["jira"] = _run_scan("jira", tmpdir, do_upload)

        if "slack" in platforms:
            results["slack"] = _run_scan("slack", tmpdir, do_upload)

    return json.dumps({"status": "complete", "results": results}), 200


def _run_scan(platform: str, tmpdir: str, upload: bool) -> dict:
    """Run a single platform scan."""
    try:
        if platform == "jira":
            from scanners.jira_scanner import JiraScanner
            scanner = JiraScanner()
        elif platform == "slack":
            from scanners.slack_scanner import SlackScanner
            scanner = SlackScanner()
        else:
            return {"status": "error", "message": f"Unknown platform: {platform}"}

        df = scanner.scan()
        filepath = os.path.join(tmpdir, f"{platform}_access_review.csv")
        df.to_csv(filepath, index=False)

        gcs_uri = ""
        if upload:
            from scanners.config import upload_csv_to_gcs
            gcs_uri = upload_csv_to_gcs(filepath, platform)

        return {
            "status": "ok",
            "rows": len(df),
            "gcs_uri": gcs_uri,
        }
    except Exception as e:
        logger.error(f"{platform} scan failed: {e}")
        return {"status": "error", "message": str(e)}
