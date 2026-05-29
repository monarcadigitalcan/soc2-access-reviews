# Jira & Slack Access Review — Architecture

## Overview

Automated access scanning for Jira Cloud and Slack, producing CSV reports for human review. Designed to run on a GCP VM today (Phase 1) and migrate to Cloud Functions behind a secure web frontend (Phase 2).

## Workflow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│  Scan       │────▶│  CSV to GCS  │────▶│  Human Review    │────▶│  Revoke      │
│  (automated)│     │  Bucket      │     │  (edit CSVs)     │     │  (Phase 2)   │
└─────────────┘     └──────────────┘     └─────────────────┘     └──────────────┘
       │                                         │                        │
       │                                         │                        │
  Jira REST API                            Web UI / local            Jira REST API
  Slack API                                                         Slack Admin API
  Offboarding DB (Phase 2)                                          Offboarding DB
```

## Phases

### Phase 1 — VM Scripts (Current)
- Python scripts running on existing GCP VM (same as GDrive review scripts)
- Credentials stored in GCP Secret Manager
- CSV output to GCS bucket (`gs://<project>-compliance-reviews/`)
- Manual execution via CLI or cron
- Revocation: **manual** (human performs revocations based on reviewed CSVs)

### Phase 2 — Cloud Functions + Web Frontend
- Same scanner modules, wrapped with HTTP handlers
- Triggered from a secure web frontend
- **Offboarding integration**: a separate app records departed employees in a database
  - Scanners query this DB at scan time to auto-flag departed users
  - Departed users go through automatic revocation (no human review needed)
- Revocation scripts activated for auto-revoke of departed employees
- Reviewed CSVs can also be submitted for batch revocation via the web UI

## Project Structure

```
jira-slack-access-managers/
├── scanners/
│   ├── __init__.py
│   ├── config.py            # GCP Secret Manager + GCS client
│   ├── jira_scanner.py      # Jira Cloud access enumeration
│   ├── slack_scanner.py     # Slack workspace access enumeration
│   └── csv_schema.py        # Shared CSV column definitions
├── cloud_functions/
│   ├── main.py              # Cloud Function HTTP entry point (Phase 2)
│   └── requirements.txt
├── tests/
│   └── ...
├── docs/
│   ├── ARCHITECTURE.md      # This file
│   └── GCP_SETUP.md         # Bucket + Secret Manager provisioning guide
├── cli.py                   # VM entry point (cron / manual)
├── requirements.txt
├── .env.example             # Local dev reference (not used in prod)
└── .gitignore
```

## CSV Schema

| Column             | Type     | Source        | Description                                           |
|--------------------|----------|---------------|-------------------------------------------------------|
| `platform`         | string   | scanner       | `jira` or `slack`                                     |
| `resource_type`    | string   | scanner       | `project`, `group`, `channel`, `workspace`            |
| `resource_name`    | string   | scanner       | Project key, group name, channel name                 |
| `resource_id`      | string   | scanner       | Platform-specific ID                                  |
| `user_email`       | string   | scanner       | User's email address                                  |
| `user_display_name`| string   | scanner       | User's display name                                   |
| `user_id`          | string   | scanner       | Platform-specific user ID                             |
| `role`             | string   | scanner       | Role/permission level                                 |
| `last_active`      | datetime | scanner       | Last activity timestamp (if available)                |
| `granted_date`     | datetime | scanner       | When access was granted (if available)                |
| `departed`         | boolean  | offboarding DB| `TRUE` if user is in the departed employees list      |
| `flagged`          | boolean  | reviewer      | `TRUE` if access should be revoked (human fills this) |
| `reviewer_notes`   | string   | reviewer      | Free-text notes from human reviewer                   |
| `revoke_status`    | string   | revoke script | `pending`, `success`, `failed`, `skipped`             |
| `revoke_date`      | datetime | revoke script | When revocation was executed                          |

## Credentials Required

### Jira Cloud
- **API Token**: Created at https://id.atlassian.com/manage-profile/security/api-tokens
- **Auth method**: Basic Auth (`email:api_token` base64-encoded)
- **Scopes needed**: Read access to all projects, users, groups, and roles
- **Secret Manager key**: `jira-access-review-token`
- **Additional secret**: `jira-admin-email` (the admin email used with the token)

### Slack
- **Bot Token** (`xoxb-`): Created via a Slack App at https://api.slack.com/apps
- **Required bot scopes**: `users:read`, `users:read.email`, `channels:read`, `groups:read`
- **Secret Manager key**: `slack-access-review-bot-token`
- **Note**: These are read-only scopes. Phase 2 revocation will require `admin.*` scopes (Business+ or Enterprise Grid only).

### GCP
- **Service account** on the VM needs roles:
  - `roles/secretmanager.secretAccessor` (read secrets)
  - `roles/storage.objectAdmin` (write CSVs to GCS bucket)
- **For Cloud Functions (Phase 2)**: same roles via the function's service account

## Security Considerations

- No credentials in code or git — all secrets in GCP Secret Manager
- GCS bucket should have uniform bucket-level access (no ACLs)
- Enable GCS Object Versioning for audit trail
- Cloud Function (Phase 2) should require IAP or Firebase Auth — no public access
- Slack bot token is scoped read-only for Phase 1
- All API calls should be logged for audit purposes

## Future: Offboarding Integration (Phase 2)

The offboarding app will maintain a database table of departed employees:

```sql
-- Conceptual schema
CREATE TABLE departed_employees (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    departure_date DATE NOT NULL,
    department VARCHAR(255),
    recorded_at TIMESTAMP DEFAULT NOW(),
    quarter VARCHAR(7)  -- e.g., '2026-Q1'
);
```

At scan time, the scanners will:
1. Query this table for employees departed in the current + previous quarter
2. Auto-set `departed = TRUE` in the CSV for matching users
3. Phase 2 revoke scripts will auto-process rows where `departed = TRUE` without waiting for human review
