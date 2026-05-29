import csv
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIGURATION ===
SERVICE_ACCOUNT_FILE = "service_account.json"
DELEGATED_EMAIL = os.getenv("DELEGATED_EMAIL", "reviewer@acme.example.com")
STALE_CSV_FILE = "input/review_stale_external_access.csv"
REVIEW_OUTPUT_FILE = "output/action_required_folder_permissions.csv"


def find_sources():
    print("Authenticating...")
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    delegated_creds = creds.with_subject(DELEGATED_EMAIL)
    service = build("drive", "v3", credentials=delegated_creds)

    sources_found = {}  # Use a dictionary to avoid duplicate folder rows

    print(f"Reading stale files from {STALE_CSV_FILE}...")
    try:
        with open(STALE_CSV_FILE, encoding="utf-8") as infile:
            reader = csv.DictReader(infile)
            for row in reader:
                file_id = row.get("File ID")
                target_email = row.get("Email/Domain")

                if not file_id or not target_email:
                    continue

                try:
                    # Request the specific permissionDetails field to find the inheritance source
                    results = (
                        service.permissions()
                        .list(
                            fileId=file_id,
                            fields="permissions(id, emailAddress, permissionDetails)",
                            supportsAllDrives=True,
                        )
                        .execute()
                    )

                    for perm in results.get("permissions", []):
                        if perm.get("emailAddress", "").lower() == target_email.lower():
                            details = perm.get("permissionDetails", [])

                            # Check if it's inherited
                            if details and "inheritedFrom" in details[0]:
                                source_id = details[0]["inheritedFrom"]

                                # Fetch the name of the source folder/drive so the human knows what it is
                                try:
                                    source_meta = (
                                        service.files()
                                        .get(fileId=source_id, fields="name, mimeType", supportsAllDrives=True)
                                        .execute()
                                    )
                                    source_name = source_meta.get("name")
                                except Exception:
                                    source_name = "Unknown/Inaccessible Folder"

                                # Create a unique key so we only list each folder/email combo once
                                unique_key = f"{source_id}_{target_email}"
                                sources_found[unique_key] = {
                                    "Source Name": source_name,
                                    "Source ID": source_id,
                                    "Target Email": target_email,
                                    "Triggered By Stale File ID": file_id,
                                }
                            else:
                                print(f"File {file_id} has a DIRECT permission. Handled by previous script.")
                except Exception as e:
                    print(f"Error checking file {file_id}: {e}")

        # Write the results for human review
        with open(REVIEW_OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as outfile:
            fields = ["Source Name", "Source ID", "Target Email", "Triggered By Stale File ID"]
            writer = csv.DictWriter(outfile, fieldnames=fields)
            writer.writeheader()
            for row in sources_found.values():
                writer.writerow(row)

        print(f"\nDone! Found {len(sources_found)} parent folders/drives that require review.")
        print(f"Please review and edit '{REVIEW_OUTPUT_FILE}', then run Step 2.")

    except FileNotFoundError:
        print(f"Error: Could not find '{STALE_CSV_FILE}'.")


if __name__ == "__main__":
    find_sources()
