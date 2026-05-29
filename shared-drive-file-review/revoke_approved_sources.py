import csv
import os
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIGURATION ===
SERVICE_ACCOUNT_FILE = "service_account.json"
DELEGATED_EMAIL = os.getenv("DELEGATED_EMAIL", "reviewer@acme.example.com")
APPROVED_CSV_FILE = "input/action_required_folder_permissions.csv"  # The file you just manually edited
EVIDENCE_CSV_FILE = "output/evidence_folder_revoked.csv"


def revoke_approved_sources():
    print(f"Loading approved revocations from: {APPROVED_CSV_FILE}")
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    delegated_creds = creds.with_subject(DELEGATED_EMAIL)
    service = build("drive", "v3", credentials=delegated_creds)

    try:
        with (
            open(APPROVED_CSV_FILE, encoding="utf-8") as infile,
            open(EVIDENCE_CSV_FILE, mode="w", newline="", encoding="utf-8") as outfile,
        ):
            reader = csv.DictReader(infile)
            writer = csv.DictWriter(
                outfile, fieldnames=["Timestamp", "Source Name", "Source ID", "Target Email", "Action"]
            )
            writer.writeheader()

            for row in reader:
                source_id = row.get("Source ID")
                target_email = row.get("Target Email")
                source_name = row.get("Source Name")

                if not source_id or not target_email:
                    continue

                print(f"Processing Folder: {source_name} | Target: {target_email}")

                try:
                    # 1. Fetch active permissions for the parent folder
                    results = (
                        service.permissions()
                        .list(fileId=source_id, fields="permissions(id, emailAddress)", supportsAllDrives=True)
                        .execute()
                    )

                    perm_id_to_delete = None
                    for perm in results.get("permissions", []):
                        if perm.get("emailAddress", "").lower() == target_email.lower():
                            perm_id_to_delete = perm.get("id")
                            break

                    if not perm_id_to_delete:
                        print(" -> SKIP: Active permission not found. Already removed.")
                        continue

                    # 2. Execute Deletion
                    service.permissions().delete(
                        fileId=source_id, permissionId=perm_id_to_delete, supportsAllDrives=True
                    ).execute()

                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f" -> SUCCESS: Revoked access for {target_email}")

                    writer.writerow(
                        {
                            "Timestamp": timestamp,
                            "Source Name": source_name,
                            "Source ID": source_id,
                            "Target Email": target_email,
                            "Action": "REVOKED_APPROVED_FOLDER_ACCESS",
                        }
                    )
                    outfile.flush()

                except Exception as e:
                    print(f" -> ERROR on folder {source_id}: {e}")

    except FileNotFoundError:
        print(f"Error: Could not find '{APPROVED_CSV_FILE}'. Did you finish the manual review?")


if __name__ == "__main__":
    revoke_approved_sources()
