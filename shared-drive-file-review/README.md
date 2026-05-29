# Shared Drive SOC 2 Audit Toolkit

Google Shared Drive permission auditing and remediation toolkit for SOC 2 compliance at Acme Analytics. This README is the entry point for whoever takes over the quarterly access review.

If you're new: read this top-to-bottom once, then keep it open as a runbook.

---

## 1. What this toolkit does

Every quarter, SOC 2 requires evidence that:
1. We know **who has access** to every shared drive.
2. We **revoke access** that is stale, external, or inappropriate.
3. We can **prove** we did it (before/after CSVs).

These scripts produce that evidence. They talk to the Google Drive API v3 via a service account with domain-wide delegation that impersonates a Workspace super admin.

There is no package manager, no test suite, and no CI. Each script is standalone Python and writes CSV artifacts that the next script consumes.

---

## 2. Prerequisites

- **Python 3.9+**
- **Pip dependencies**:
  ```bash
  pip install google-auth google-api-python-client pandas
  ```
- **A `service_account.json`** key file in the project root (see §3).
- **Workspace super admin** identity to impersonate (see §3).
- macOS or Linux shell. Examples below use `bash`/`zsh`.

---

## 3. Credentials & Setup (do this first)

The toolkit impersonates a Google Workspace super admin via a service account with domain-wide delegation. Configure it as follows:

### 3.1 Confirm your impersonation identity
You need a **Google Workspace super admin** in your tenant. Without super admin, the Drive API returns `403 insufficientFilePermissions` when touching shared drives owned by other teams. Confirm with IT before continuing.

### 3.2 Rotate the service account key
The service account itself can stay; only the JSON key rotates.

1. Open the GCP project that owns the service account → **IAM & Admin → Service Accounts**.
2. Locate the service account referenced by the existing `service_account.json` (its `client_email` is in the file).
3. **Keys** tab → **Add Key → Create new key → JSON**. Download.
4. Save the downloaded file as `service_account.json` in the project root, replacing the existing one.
5. Verify it is **not committed** (it's gitignored, but double-check).
6. After your first successful audit run, **delete the previous key** in the GCP console — that invalidates the outgoing admin's credentials.

### 3.3 Verify domain-wide delegation
In the Google Workspace Admin console:

**Security → Access and data control → API controls → Domain-wide delegation**

Confirm the service account's **Client ID** (numeric, found as `client_id` in `service_account.json`) is authorized for exactly this scope:

```
https://www.googleapis.com/auth/drive
```

If you reused the existing SA, no change is needed. If you created a new SA, add a new entry with its Client ID and the scope above.

### 3.4 Set the impersonated admin email
Each script reads the delegated user from an environment variable (`DELEGATED_EMAIL`, and `IMPERSONATED_USER` for `audit_report_3.py` / `access_revoke.py`), falling back to a placeholder default. Export your super-admin email before running:

```bash
export DELEGATED_EMAIL="your-admin@your-domain.com"
export IMPERSONATED_USER="your-admin@your-domain.com"
```

(Or edit the default in each script's `# === CONFIGURATION ===` block if you prefer.)
`audit_report_3.py` also has an `INTERNAL_DOMAIN` constant — set it to the domain you treat as internal (everything else is flagged external).

### 3.5 Smoke test
Run a small audit and Ctrl-C after a few rows print:

```bash
python audit_report_3.py
```

- `unauthorized_client` → delegation (3.3) is wrong.
- `403 insufficientFilePermissions` → your impersonated user isn't a super admin (3.1).
- Rows streaming to the CSV → you're good.

### 3.6 Record it
Note the configured admin email and the date in your SOC 2 evidence records.

---

## 4. Repository layout

```
shared-drive-file-review/
├── README.md                       ← you are here
├── CLAUDE.md / AGENTS.md           ← guidance for AI coding assistants
├── service_account.json            ← GCP service account key (gitignored)
├── input/                          ← curated CSVs that feed scripts
│   ├── revoke_external.csv
│   ├── review_stale_external_access.csv
│   └── emails_revoke.txt
├── output/                         ← evidence CSVs and traced sources
│   ├── evidence_external_revoked.csv
│   ├── evidence_stale_revoked.csv
│   ├── evidence_inherited_revoked.csv
│   ├── traced_stale_sources.csv
│   ├── traced_sources.csv
│   ├── pending_inherited_permissions.csv
│   ├── handoff_manual_revoke_final.csv
│   ├── accepted_risk_externally_managed.csv
│   ├── stale_skipped.csv
│   └── report_input_q<N>_<FY>.md
└── *.py                            ← the scripts
```

**Convention:** scripts with the `_v2` suffix are the **current** versions. The un-suffixed older versions are kept for reference only — do not run them.

---

## 5. Scripts: latest vs legacy

### Use these (current)

| Phase | Script | Purpose |
|---|---|---|
| 1. Audit | `audit_report_3.py` | Crawls every shared drive, resolves folder paths, writes a full permission report. Flags external (non-`acme.example.com`) and skips internal staff on "Customers" drives to reduce noise. |
| 2. Analyze | `soc2_analyzer.py` | Diffs a BEFORE vs AFTER audit CSV → `evidence_remediated_access.csv` (proof of removal) + `review_stale_external_access.csv` (>180 days old). |
| 2b. Stale only | `stale_analyzer.py` | Subset of the analyzer; only runs the stale-detection pass. |
| 3. Revoke direct external | **`revoke_external_v2.py`** | Reads `input/revoke_external.csv`, revokes direct external permissions, writes `output/evidence_external_revoked.csv`. |
| 4. Revoke + trace stale | **`revoke_stale_sources_v2.py`** | Reads `input/review_stale_external_access.csv`. Dedupes by (email, perm_type), traces each to its source folder, writes `traced_stale_sources.csv`, `evidence_stale_revoked.csv`, `stale_skipped.csv`. |
| 5. Revoke inherited | **`find_and_revoke_sources_v2.py`** | Reads `output/pending_inherited_permissions.csv` (curated by you), traces inheritance, revokes at the source folder, writes `traced_sources.csv`, `evidence_inherited_revoked.csv`. |

### Do NOT use (legacy / superseded)
- `revoke_stale_access.py` → replaced by `revoke_stale_sources_v2.py`
- `find_permission_sources.py` + `revoke_approved_sources.py` → merged into `find_and_revoke_sources_v2.py`

### One-off
- `access_revoke.py` — bulk revokes for a list of emails in `input/emails_revoke.txt`. Useful for offboarding. **No dry-run mode** — it deletes immediately. See §7 for the full procedure.

---

## 6. Standard quarterly run order

This is the workflow you'll execute every quarter. Each step's output feeds the next.

### Step 1 — BEFORE snapshot
```bash
python audit_report_3.py
```
Produces `audit_verification_final.csv` (rename/archive it as `audit_before_q<N>.csv`).

### Step 2 — Analyze
Run the analyzer with the BEFORE snapshot and the prior quarter's AFTER snapshot:
```bash
python soc2_analyzer.py
```
Produces:
- `review_stale_external_access.csv` → external shares older than 180 days
- `evidence_remediated_access.csv` → diff between snapshots (closes last quarter's loop)

### Step 3 — Triage direct external shares
Open the audit CSV. Build `input/revoke_external.csv` from the rows that need direct external access removed. Then:
```bash
python revoke_external_v2.py
```

### Step 4 — Triage stale (>180 day) external shares
```bash
python revoke_stale_sources_v2.py
```
This auto-dedupes the input and traces each permission. Watch for entries written to `output/pending_inherited_permissions.csv` — those need manual review (next step).

### Step 5 — Manual review of inherited permissions
Open `output/pending_inherited_permissions.csv`:
- **Approve** revocation → leave the row in the file.
- **Externally managed** (e.g., a client owns the parent folder) → move row to `output/accepted_risk_externally_managed.csv`.
- **Cannot revoke programmatically** → move row to `output/handoff_manual_revoke_final.csv` for manual cleanup in the Drive UI.

This is the only step that requires judgment. Take your time.

### Step 6 — Revoke at folder level
```bash
python find_and_revoke_sources_v2.py
```
Revokes the curated inherited permissions at the source folder.

### Step 7 — AFTER snapshot
```bash
python audit_report_3.py
```
Archive as `audit_after_q<N>.csv`.

### Step 8 — Final analyzer pass
Run `soc2_analyzer.py` again with BEFORE + AFTER from this quarter to produce the final remediation evidence.

### Step 9 — Manual cleanup
Work through `output/handoff_manual_revoke_final.csv` in the Drive UI for anything the API couldn't handle.

### Step 10 — Build the formal report
Pull `output/report_input_q<N>_<FY>.md` and the evidence CSVs into your SOC 2 report template (e.g. under `~/soc2-evidence/`), then attach the final write-up to your audit tracker.

---

## 7. Off-cycle: revoking access for a departed employee

When IT offboards someone (or a contractor's engagement ends), use `access_revoke.py` to strip their access from every shared drive in one pass. This is **independent of the quarterly review** — run it whenever an offboarding ticket comes in.

### What it does
Iterates every file the service account can see across all shared drives, lists each file's permissions, and deletes any permission whose email matches an entry in `input/emails_revoke.txt`. Writes evidence to `output/remediation_evidence.csv`.

### Procedure

1. **Get the email list from IT.** Confirm the person is actually offboarded — this is destructive and there is **no dry-run**.

2. **Edit `input/emails_revoke.txt`.** One email per line, no quotes, no commas. Blank lines are ignored. Example:
   ```
   former.employee@acme.example.com
   contractor@external-domain.com
   ```

3. **(Recommended) Take a BEFORE snapshot** so you can include the revocation in the next SOC 2 evidence pack:
   ```bash
   python audit_report_3.py
   ```
   Archive the resulting CSV.

4. **Run the revocation:**
   ```bash
   python access_revoke.py
   ```
   It streams `[timestamp] REMOVED <email> from <file>` lines as it works. The script is long-running (it scans every file in the tenant) — for a large tenant this can take 30+ minutes. Safe to leave running; evidence is flushed per row.

5. **Verify with `output/remediation_evidence.csv`.** Columns: `Timestamp, Target Email, File Name, File ID, Status`. Each row is one revoked permission. If the file is empty, the emails were already gone (or misspelled — check the list).

6. **Archive the evidence.** Rename to `evidence_offboarding_<email>_<YYYY-MM-DD>.csv` and store alongside the quarterly evidence in `~/soc2-evidence/`. Reference it in the next SOC 2 report.

7. **Clear the input file** (or comment out lines) so the next offboarding run doesn't re-process the same list.

### Caveats
- The script silently skips files it can't manage (e.g., personal drives the SA can't reach). That's expected — the `try/except` around each file is intentional.
- Group memberships are **not** handled here. If the user is in a Google Group that has Drive access, removing them from the group is IT's job. This script only revokes direct per-file/per-folder permissions.
- Permissions inherited from a parent folder where the user is also a direct member: the direct grant is removed; the inherited grant must be handled by removing them from the parent (or use `find_and_revoke_sources_v2.py` for that).

---

## 8. CSV schema

All audit CSVs share this column set:

```
Flagged External, Shared Drive Name, File Name, Modified Date,
Folder Path, Permission Type, Role, Email/Domain, File ID, Link
```

Evidence CSVs add a `Timestamp`, `Action`, and `Reason` column.

---

## 9. Implementation notes (worth knowing)

- All Drive API calls pass `supportsAllDrives=True` and `includeItemsFromAllDrives=True`. Without these flags shared drives are invisible.
- Folder paths are resolved recursively with an in-memory cache (`folder_path_cache`) — the first audit pass is slow, subsequent ones reuse cache.
- Evidence CSVs are flushed after each row write, so Ctrl-C during a long revoke is safe — the file reflects what actually completed.
- Permission matching is by lowercased email, deletion is by permission ID.
- `revoke_stale_access.py` (legacy) has a `DRY_RUN = True` toggle. The `_v2` scripts do not — they execute immediately, so verify your input CSV before running.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `unauthorized_client` | Domain-wide delegation not configured for the SA's Client ID | §3.3 |
| `403 insufficientFilePermissions` | Impersonated user is not a super admin | §3.1 |
| `404 File not found` during revoke | File deleted between audit and revoke; or no access on personal drive | Skip and log |
| Audit hangs on a specific drive | Large drive + cold folder cache | Let it run; subsequent passes are faster |
| Empty `evidence_*.csv` after revoke | Input CSV had no matching permissions (already revoked, or email mismatch) | Re-audit and confirm the email is still on the file |
| `quotaExceeded` / `userRateLimitExceeded` | Hit Drive API quota | Wait 60s and re-run; the script is idempotent |

---

## 11. Reference: report format

See `output/report_input_sample.md` for an example narrative report (synthetic data) summarizing a remediation cycle — copy that structure for your own runs.

---

## 12. Quick rules of thumb

- When in doubt, run the `_v2` script.
- Never skip the BEFORE/AFTER audit pair — that's the SOC 2 evidence trail.
- Manual review (§6 Step 5) is the only step that requires judgment. Don't rush it.
- Anything the API can't revoke is not a failure — log it to `handoff_manual_revoke_final.csv` and clean up in the UI.
