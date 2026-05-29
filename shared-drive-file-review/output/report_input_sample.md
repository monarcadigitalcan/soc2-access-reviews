# Shared Drive Access Review — Q2 (Sample / Synthetic Data)

> This is an **example** evidence report built from synthetic data. Use it as a template for the formal write-up you attach to your SOC 2 evidence pack. All names, emails, file IDs, and figures below are fictional.

## Scope

This review covers **Google Drive** (Shared Drives and My Drive). It was conducted with automated scripts using a Google Workspace service account (`access-reviewer@your-gcp-project.iam.gserviceaccount.com`) impersonating a super admin via domain-wide delegation.

- External access flagged by domain (non-`acme.example.com`).
- BEFORE/AFTER audit snapshots taken with `audit_report_3.py`.

## Remediation summary

| Metric | Count |
|---|---|
| Permissions audited | 1,840 |
| External permissions revoked (direct) | 31 |
| Stale (>180 day) external permissions revoked | 18 |
| Inherited permissions revoked at source folder | 9 |
| Handed off for manual cleanup | 4 |

## Examples of revoked external access

| File / Folder | Email | Reason |
|---|---|---|
| Vendor Integration Spec | partner@vendor.example.net | Engagement ended |
| Globex SOW | contractor@contoso.example.com | Old engagement |
| Brand Assets | partner-agency.example.org | External access no longer needed |

## Accepted risk (externally managed)

| Item | Reason |
|---|---|
| Customer-owned shared folder | Parent folder owned by client; cannot revoke programmatically |

## Sign-off

- Reviewer: _<name>_
- Date: _<YYYY-MM-DD>_
- Evidence files: `evidence_*_revoked.csv` + BEFORE/AFTER audit CSVs in `output/`.
