# Jira & Slack Access Review Manager

Quarterly SOC2 access review tooling for Acme Analytics. Scans Jira Cloud and Slack workspaces, produces CSV reports for human review, and revokes access for departed employees.

> **Operational note:** This tool is run quarterly. Each cycle takes ~1 day end-to-end (most of that is the human review step). Outputs in `output/` are SOC2 evidence — never delete past quarters' files.

---

## TL;DR — quarterly run

```bash
# 1. Scan
python cli.py scan --all --upload

# 2. Open the two CSVs in output/, mark each row as OFFBOARD or KEEP in
#    the revoke_status column, then save.

# 3. Dry run, then real run
python cli.py revoke output/jira_access_review_<date>.csv  --platform jira  --dry-run
python cli.py revoke output/jira_access_review_<date>.csv  --platform jira
python cli.py revoke output/slack_access_review_<date>.csv --platform slack --dry-run
python cli.py revoke output/slack_access_review_<date>.csv --platform slack
```

---

## What this tool does

Three-step quarterly workflow:

1. **Scan** — enumerates all users + their access in Jira and Slack, writes a CSV.
2. **Review** — a human (you) marks each row `OFFBOARD` (revoke) or `KEEP` (legitimate).
3. **Revoke** — the tool reads the reviewed CSV and removes access for `OFFBOARD` rows.

The reviewed CSVs and revoke evidence files in `output/` are the SOC2 audit artifacts.

---

## Repository layout

| Path | Purpose |
|---|---|
| `cli.py` | Single entry point. Subcommands: `scan`, `revoke` |
| `scanners/jira_scanner.py` | Enumerates Jira users, projects, roles, apps |
| `scanners/slack_scanner.py` | Enumerates Slack users + channel membership |
| `scanners/jira_revoker.py` | Removes Jira access per `OFFBOARD` row |
| `scanners/slack_revoker.py` | Slack revocation (partial — see caveats below) |
| `scanners/config.py` | Secret Manager + `.env` resolution, GCS upload |
| `scanners/csv_schema.py` | Shared CSV column contract |
| `cloud_functions/` | Phase 2 HTTP wrapper (not in production yet — ignore for now) |
| `docs/` | Architecture, GCP setup, migration notes |
| `input/` | Reference material from past reviews (manual checklists, report templates) — not read by any script |
| `output/` | Generated CSVs + SOC2 evidence files |
| `.env.example` | Template for local credential setup |

---

## First-time setup

### 1. Clone and install

```bash
git clone <repo-url> jira-slack-access-managers
cd jira-slack-access-managers
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Requires Python 3.10+.

### 2. Credentials

The tool resolves credentials in this order:
1. **Environment variables** (set via `.env` for local dev)
2. **GCP Secret Manager** (used in production / on the GCP VM)

For local development, the easiest path is `.env`. Copy the template and fill it in:

```bash
cp .env.example .env
```

Then edit `.env`. You need six values:

| Variable | What it is | Where to get it |
|---|---|---|
| `GCP_PROJECT_ID` | The GCP project that holds Secret Manager + the GCS bucket | Check `gcloud config list`, or ask your GCP admin |
| `GCS_BUCKET_NAME` | Bucket where uploaded CSVs land | Format is usually `<project-id>-compliance-reviews` |
| `JIRA_SITE_URL` | `https://acme.atlassian.net` | Already correct in `.env.example` |
| `JIRA_ADMIN_EMAIL` | Email of the Jira admin user whose token you're using | Your Jira site-admin account |
| `JIRA_ACCESS_REVIEW_TOKEN` | Jira API token | See "Generating a Jira API token" below |
| `SLACK_ACCESS_REVIEW_BOT_TOKEN` | Slack bot token, starts with `xoxb-` | See "Slack bot token" below |

> The env var names map to Secret Manager keys by lowercasing and converting `_` to `-`. For example, `JIRA_ACCESS_REVIEW_TOKEN` maps to the secret `jira-access-review-token`. If a value is set in `.env`, it takes precedence over Secret Manager.

#### Generating a Jira API token

1. Log into Jira as a **site admin** (the access review needs admin scope to enumerate all projects/users).
2. Go to <https://id.atlassian.com/manage-profile/security/api-tokens>.
3. Click **Create API token**, label it `access-review-<your-name>`, copy the value into `.env` as `JIRA_ACCESS_REVIEW_TOKEN`.
4. Set `JIRA_ADMIN_EMAIL` to the same admin's email.

Store the token in GCP Secret Manager as `jira-access-review-token` (or in `.env` for local dev). Generate it under a dedicated admin account so it can be rotated independently of any individual.

#### Slack bot token

Create (or reuse) a Slack app named `Access Review Bot` in your workspace. To use it:

1. Go to <https://api.slack.com/apps>, sign in with your workspace admin account.
2. Open the **Access Review Bot** app (ask a workspace admin to add you as a collaborator if you don't see it).
3. **OAuth & Permissions** → copy the **Bot User OAuth Token** (`xoxb-...`) into `.env` as `SLACK_ACCESS_REVIEW_BOT_TOKEN`.

Required scopes (already configured): `users:read`, `users:read.email`, `channels:read`, `groups:read`, `usergroups:read`. For the revoker to leave channels, the bot must also have `channels:join` and be a member of the channel.

#### GCP authentication (for Secret Manager and GCS upload)

If you'd rather not use `.env` and want to use Secret Manager directly, authenticate gcloud:

```bash
gcloud auth application-default login
gcloud config set project <GCP_PROJECT_ID>
```

You'll need the IAM roles `roles/secretmanager.secretAccessor` and `roles/storage.objectAdmin` on the bucket. A GCP project owner can grant these.

### 3. Verify setup

```bash
source venv/bin/activate
python -c "from scanners.config import get_secret; print(get_secret('jira-access-review-token')[:10] + '...')"
```

If that prints the first 10 characters of your Jira token, credentials work.

---

## Running a quarterly review

### Step 1 — Scan

```bash
python cli.py scan --all --upload
```

Flags:
- `--jira` / `--slack` / `--all` — pick what to scan
- `--upload` — also push CSVs to `gs://<bucket>/access-reviews/<date>/`
- `--output-dir <path>` — override the default `./output`

Outputs:
- `output/jira_access_review_<YYYY-MM-DD>.csv`
- `output/slack_access_review_<YYYY-MM-DD>.csv`

### Step 2 — Human review

Open each CSV (Excel, Google Sheets, whatever). For each row, set the `revoke_status` column to one of:

| Value | Meaning |
|---|---|
| `OFFBOARD` | User has departed — revoke this access |
| `KEEP` | Legitimate access — leave as-is |
| *(blank)* | Treated as skip; safer to be explicit |

You can also fill `reviewer_notes` with context (e.g. "left 2026-03-15, confirmed in HRIS").

> **Convention:** We use `OFFBOARD`/`KEEP` strings, not the `flagged` boolean column. The `flagged` and `departed` columns are scanner artifacts — ignore them for decision-making.

> **Manual checklist:** `input/emails_revoke.txt` is a plain list of departed-employee emails kept from the previous cycle. It is **not** read by any script — it's just a hand reference to speed up the human review step. When you start a new cycle, ask HR for the current departed list and either replace this file or keep your own. The tool only acts on `revoke_status` values in the reviewed CSV.

> **Clean evidence:** Keep `reviewer_notes` tidy. Don't leave noise like "scanner picked up disabled user" — explain and dismiss in the notes so the SOC2 auditor doesn't ask.

### Step 3 — Dry run, then revoke

**Always dry-run first.**

```bash
python cli.py revoke output/jira_access_review_<date>.csv  --platform jira  --dry-run
python cli.py revoke output/slack_access_review_<date>.csv --platform slack --dry-run
```

Inspect the `dryrun_*_revoke_results_<date>.csv` output. If it looks right, run for real:

```bash
python cli.py revoke output/jira_access_review_<date>.csv  --platform jira
python cli.py revoke output/slack_access_review_<date>.csv --platform slack
```

After revocation, `revoke_status` becomes `success` or `failed`, with details in `reviewer_notes` for failures.

### Step 4 — Compile SOC2 evidence

The evidence package for the auditor is a markdown report combining the reviewed CSVs and revoke results. See `input/report_input_sample.md` for the format — copy that structure.

---

## Important caveats

### Slack revocation is partial

Acme Analytics is on the Slack **Standard** plan, which **does not allow automated user deactivation** via API. The revoker can:
- ✅ Remove the bot from channels (if it has `channels:join` and is a member)
- ✅ Kick users from public channels (with the right scopes)
- ❌ Deactivate users at the workspace level — **must be done manually** via Slack admin UI

For the Slack workspace deactivation step, the revoker emits `output/slack_manual_deactivate_users_<date>.csv` listing users that need manual action. See last quarter's file for the format.

### Phase 2 is not deployed

`cloud_functions/main.py` and the planned web frontend are scaffolded but not in production. Everything currently runs from the CLI on the GCP VM (or your laptop).

### No tests

`tests/` is empty. The tool's safety net is **always running `--dry-run` first** before any revoke.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `RuntimeError: GCP_PROJECT_ID not set` | `.env` not loaded — check it's in repo root and you ran from there |
| Jira `401 Unauthorized` | Token expired, or `JIRA_ADMIN_EMAIL` doesn't match the token's owner |
| Slack `not_authed` / `invalid_auth` | Bot token rotated or scopes missing — re-check OAuth & Permissions page |
| GCS upload fails | Missing `roles/storage.objectAdmin` on the bucket, or wrong `GCS_BUCKET_NAME` |
| `revoke_status` column is `nan` after read | Old CSV — the CLI now coerces these to empty strings, but make sure the column exists |

---

## Further reading

- `docs/ARCHITECTURE.md` — how scanners and revokers are structured
- `docs/GCP_SETUP.md` — Secret Manager + bucket provisioning
- `input/report_input_sample.md` — example SOC2 evidence report (synthetic data)
