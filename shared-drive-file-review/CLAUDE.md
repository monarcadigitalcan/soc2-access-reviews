# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Google Shared Drive permission auditing and remediation toolkit for SOC 2 compliance at Acme Analytics. These are standalone Python scripts (no package manager, no tests) that interact with the Google Drive API v3 via a service account with domain-wide delegation.

## Running Scripts

All scripts are run directly with Python:
```
python <script_name>.py
```

**Dependencies:** `google-auth`, `google-api-python-client`, `pandas` (for analyzers only).

**Authentication:** Every script expects a `service_account.json` file in the working directory. The service account impersonates `reviewer@acme.example.com` using domain-wide delegation with the `https://www.googleapis.com/auth/drive` scope.

## Setup: Configuring Admin Credentials

To run this toolkit, provide two things: a **service account key** and the **impersonated user** it acts as. The same setup applies when rotating credentials later (rotate the key, keep or swap the impersonated identity).

### 1. Pick the impersonated admin
Must be a Google Workspace **super admin** in your tenant (required to read/modify permissions on every shared drive). Confirm with IT before proceeding.

### 2. Rotate the service account key
1. Open the GCP project that owns the service account → IAM & Admin → Service Accounts.
2. Locate the service account currently referenced by `service_account.json` (its `client_email` is in that file).
3. **Keys** tab → **Add Key → Create new key → JSON**. Download.
4. Save the new file as `service_account.json` in the project root, replacing the old one. Do **not** commit it (already gitignored, but verify).
5. After the next successful audit run, **delete the previous key** from the GCP console to invalidate the outgoing admin's credentials.

### 3. Verify domain-wide delegation
In the Google Workspace Admin console → **Security → Access and data control → API controls → Domain-wide delegation**, confirm the service account's **Client ID** (numeric, found in `service_account.json` as `client_id`) is authorized for the scope:

```
https://www.googleapis.com/auth/drive
```

If the service account is reused, no change is needed here. If a new service account was created, add a new entry with that Client ID and scope.

### 4. Set the impersonated email
Each script reads the delegated user from an environment variable (variable name varies — `DELEGATED_EMAIL`, or `IMPERSONATED_USER` for `audit_report_3.py` / `access_revoke.py`), falling back to a placeholder default. Export it before running:

```bash
export DELEGATED_EMAIL="your-admin@your-domain.com"
export IMPERSONATED_USER="your-admin@your-domain.com"
```

Alternatively, edit the default in each script's `# === CONFIGURATION ===` block. Also set `INTERNAL_DOMAIN` in `audit_report_3.py` to your internal domain.

### 5. Smoke test
Run `audit_report_3.py` against a single small shared drive (or let it run and Ctrl-C after the first few rows) to confirm:
- No `401`/`403` from the Drive API.
- The output CSV is being written.

If you see `unauthorized_client`, the delegation step (#3) is wrong. If you see `403 insufficientFilePermissions`, the impersonated user is not a super admin.

### 6. Record it
- Note the configured admin email and date in your SOC 2 evidence records.

## Architecture and Workflow

The scripts form a multi-phase audit-remediate-verify pipeline. Each phase produces CSV artifacts consumed by the next.

### Phase 1: Audit
- **`audit_report_3.py`** -- Crawls all shared drives, resolves folder paths, and writes a full permission report (`audit_verification_final.csv`). Flags each permission as external/internal based on the `acme.example.com` domain. Skips internal staff on "Customers" drives to reduce noise.

### Phase 2: Analyze
- **`soc2_analyzer.py`** -- Compares BEFORE/AFTER audit CSVs to produce a remediation delta (`evidence_remediated_access.csv`) and flags stale external shares older than 180 days (`review_stale_external_access.csv`).
- **`stale_analyzer.py`** -- Stripped-down version of `soc2_analyzer.py` that only runs stale access detection (delta engine code commented out).

### Phase 3: Investigate Inheritance
- **`find_permission_sources.py`** -- Reads `review_stale_external_access.csv`, traces each stale permission back to its inherited parent folder via the `permissionDetails` field, and outputs `action_required_folder_permissions.csv` for manual review.

### Phase 4: Revoke (destructive)
- **`revoke_stale_access.py`** -- Reads `review_stale_external_access.csv` and revokes direct permissions. Has a `DRY_RUN = True` safety toggle.
- **`revoke_approved_sources.py`** -- Reads `action_required_folder_permissions.csv` (after manual review) and revokes inherited folder-level permissions. Logs evidence to `evidence_folder_revoked.csv`.
- **`access_revoke.py`** -- Bulk revokes all access for a hardcoded list of emails across all drives. Logs to `remediation_evidence.csv`. No dry-run mode.

### Supporting Files
- **`emails_revoke.txt`** -- List of email addresses targeted for bulk revocation.

## Key CSV Columns

The audit CSVs share this schema: `Flagged External, Shared Drive Name, File Name, Modified Date, Folder Path, Permission Type, Role, Email/Domain, File ID, Link`.

## Important Patterns

- All Drive API calls use `supportsAllDrives=True` and `includeItemsFromAllDrives=True` to access shared drives.
- Folder path resolution is recursive with an in-memory cache (`folder_path_cache`).
- Evidence CSVs are flushed after each write to survive interruptions.
- Revocation scripts match permissions by email address (case-insensitive) then delete by permission ID.
