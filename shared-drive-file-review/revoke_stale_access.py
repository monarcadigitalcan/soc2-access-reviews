import csv
import os
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIGURATION ===
SERVICE_ACCOUNT_FILE = "service_account.json"
DELEGATED_EMAIL = os.getenv("DELEGATED_EMAIL", "reviewer@acme.example.com")
STALE_CSV_FILE = "input/review_stale_external_access.csv"
EVIDENCE_CSV_FILE = "output/evidence_stale_revoked.csv"

# SAFETY TOGGLE: Change to False when you are ready to actually delete permissions
DRY_RUN = True


def revoke_stale_access():
    print(f"Loading target list from: {STALE_CSV_FILE}")
    if DRY_RUN:
        print("=== DRY RUN MODE: ON. No permissions will be deleted. ===")
    else:
        print("=== LIVE MODE: ON. Permissions WILL be permanently deleted. ===")
        print(f"Evidence will be saved to: {EVIDENCE_CSV_FILE}")

    # Setup the Drive API
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    try:
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        delegated_creds = creds.with_subject(DELEGATED_EMAIL)
        service = build("drive", "v3", credentials=delegated_creds)
    except Exception as e:
        print(f"Failed to authenticate: {e}")
        return

    # Prepare the Evidence Log
    evidence_fields = ["Timestamp", "File Name", "File ID", "Target Email", "Action"]

    # Open both the target list (to read) and the evidence log (to write)
    try:
        with (
            open(STALE_CSV_FILE, encoding="utf-8") as infile,
            open(EVIDENCE_CSV_FILE, mode="w", newline="", encoding="utf-8") as outfile,
        ):
            reader = csv.DictReader(infile)
            writer = csv.DictWriter(outfile, fieldnames=evidence_fields)

            # Only write the header if we are actually doing a live run
            if not DRY_RUN:
                writer.writeheader()

            for row in reader:
                file_id = row.get("File ID")
                target_email = row.get("Email/Domain")
                file_name = row.get("File Name")

                if not file_id or not target_email:
                    continue

                print(f"\nProcessing: {file_name} | Target: {target_email}")

                try:
                    # 1. Fetch active permissions
                    results = (
                        service.permissions()
                        .list(fileId=file_id, fields="permissions(id, emailAddress)", supportsAllDrives=True)
                        .execute()
                    )

                    permissions = results.get("permissions", [])
                    perm_id_to_delete = None

                    # 2. Find matching Permission ID
                    for perm in permissions:
                        if perm.get("emailAddress", "").lower() == target_email.lower():
                            perm_id_to_delete = perm.get("id")
                            break

                    if not perm_id_to_delete:
                        print(" -> SKIP: Active permission not found. Already removed.")
                        continue

                    # 3. Execute Deletion and Log Evidence
                    if DRY_RUN:
                        print(f" -> [DRY RUN] Would revoke '{target_email}' (Perm ID: {perm_id_to_delete})")
                    else:
                        service.permissions().delete(
                            fileId=file_id, permissionId=perm_id_to_delete, supportsAllDrives=True
                        ).execute()

                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        print(f" -> SUCCESS: Revoked access for {target_email}")

                        # Write the proof to our evidence CSV
                        writer.writerow(
                            {
                                "Timestamp": timestamp,
                                "File Name": file_name,
                                "File ID": file_id,
                                "Target Email": target_email,
                                "Action": "REVOKED_STALE_ACCESS",
                            }
                        )
                        # Flush to ensure it saves immediately if the script gets interrupted
                        outfile.flush()

                except Exception as e:
                    print(f" -> ERROR on file {file_id}: {e}")

    except FileNotFoundError:
        print(f"Error: Could not find '{STALE_CSV_FILE}'.")


if __name__ == "__main__":
    revoke_stale_access()
