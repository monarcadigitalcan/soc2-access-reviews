# Access Review — Q2 (Sample / Synthetic Data)

> This is an **example** evidence report built from synthetic data. Use it as a template for the formal write-up you attach to your SOC 2 evidence pack. All names, emails, and figures below are fictional.

## Scope

This review covers **Jira Cloud** (`acme.atlassian.net`) and **Slack** (`acme.slack.com`).

- **Jira**: full audit of all projects, project roles, groups, and group memberships — 1,200 access entries scanned on 2026-03-26.
- **Slack**: all workspace members and channel memberships.

Reviews were conducted with automated scanners (`cli.py scan --all`) authenticated via a Jira admin API token and a Slack bot token. A human reviewer then marked each row `OFFBOARD` or `KEEP`.

## Jira — remediation summary

| Metric | Count |
|---|---|
| Project role assignments removed (individual users) | 12 |
| Groups removed from project roles | 4 |
| Projects with role assignments cleaned up | 9 |

### Retained access (reviewed and kept)

| Project / Group | Reason |
|---|---|
| Globex Migration (admins) | Active internal engagement |
| Initech Analytics (viewers) | Active customer engagement |

## Slack — remediation summary

| Metric | Count |
|---|---|
| Accounts flagged for deactivation | 6 |
| Accounts deactivated (manual, admin console) | 6 |

> **Note:** Automated workspace deactivation requires Enterprise Grid. On the Standard plan, the tool emits a manual-deactivation list (`output/slack_manual_deactivate_users_<date>.csv`) for an admin to action in the Slack console.

### Slack Connect external users

Channel memberships from partner/vendor workspaces (e.g. `#vendor-shared`) are external accounts outside our administrative control.
**Risk disposition:** ACCEPTED — a separate shared-channel audit is recommended.

## Sign-off

- Reviewer: _<name>_
- Date: _<YYYY-MM-DD>_
- Evidence files: reviewed CSVs + `*_revoke_results_<date>.csv` in `output/`.
