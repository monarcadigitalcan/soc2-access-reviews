# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Purpose

Automated access review scanners for Jira Cloud and Slack workspaces. Produces CSV reports listing who has access to what, for human compliance review. Currently in Phase 1 (CLI on GCP VM); Phase 2 adds Cloud Functions, a web frontend, and automated revocation of departed employees.

## Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run scans
python cli.py --all              # Scan both Jira and Slack
python cli.py --jira             # Jira only
python cli.py --slack            # Slack only
python cli.py --all --upload     # Scan and upload CSVs to GCS
python cli.py --all --output-dir /path  # Custom output directory

# No test framework is configured yet (tests/ directory is empty)
```

## Architecture

Two scanners (`JiraScanner`, `SlackScanner`) share a common pattern:
1. Authenticate using credentials from GCP Secret Manager (falls back to env vars via `.env` for local dev)
2. Enumerate resources and memberships through platform APIs
3. Return a pandas DataFrame normalized to a shared CSV schema (`csv_schema.COLUMNS`)
4. CLI or Cloud Function writes the DataFrame to CSV (locally and/or to GCS)

Key data flow: `Scanner.scan()` → `pd.DataFrame` → `normalize_dataframe()` → CSV → optional GCS upload

### Credential resolution

`scanners/config.py:get_secret()` checks env vars first (secret name with dashes→underscores, uppercased), then falls back to GCP Secret Manager. The `.env` file is auto-loaded on import of `scanners.config`.

### CSV schema

All scanners output the same columns defined in `scanners/csv_schema.py`. Scanner-populated columns: platform, resource_type, resource_name, resource_id, user_email, user_display_name, user_id, role, last_active, granted_date. Reviewer/revoke columns (departed, flagged, reviewer_notes, revoke_status, revoke_date) are initialized with defaults.

### Cloud Function (Phase 2)

`cloud_functions/main.py` wraps the same scanner modules behind an HTTP endpoint using `functions-framework`. It adds the parent directory to `sys.path` to import `scanners`.

## Environment Variables

Required (set in `.env` for local dev, or as actual env vars on GCP VM):
- `GCP_PROJECT_ID` — GCP project for Secret Manager
- `GCS_BUCKET_NAME` — GCS bucket for CSV uploads
- `JIRA_SITE_URL` — e.g. `https://acme.atlassian.net`

Local dev credential fallbacks (map to Secret Manager key names):
- `JIRA_ACCESS_REVIEW_TOKEN`
- `JIRA_ADMIN_EMAIL`
- `SLACK_ACCESS_REVIEW_BOT_TOKEN`
