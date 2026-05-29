import csv
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIGURATION ===
SERVICE_ACCOUNT_FILE = "service_account.json"
IMPERSONATED_USER = os.getenv("IMPERSONATED_USER", "reviewer@acme.example.com")
INTERNAL_DOMAIN = "acme.example.com"
OUTPUT_FILE = "output/audit_verification_final.csv"  # Changed name for clarity
SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("drive", "v3", credentials=creds.with_subject(IMPERSONATED_USER))


# Caches to prevent redundant API calls
drive_names = {}
folder_path_cache = {}


def get_full_path(service, item_id):
    """Recursively builds the folder path."""
    if item_id in folder_path_cache:
        return folder_path_cache[item_id]
    try:
        res = service.files().get(fileId=item_id, fields="name, parents", supportsAllDrives=True).execute()
        parents = res.get("parents")
        if not parents:
            path = "/" + res.get("name")
        else:
            path = get_full_path(service, parents[0]) + "/" + res.get("name")
        folder_path_cache[item_id] = path
        return path
    except Exception:
        return "/Unknown"


def run_verification_audit():
    service = get_drive_service()
    print(f"Starting verification audit. Writing to: {OUTPUT_FILE}...")

    with open(OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Added 'Folder Path' to match previous cycle format
        writer.writerow(
            [
                "Flagged External",
                "Shared Drive Name",
                "File Name",
                "Modified Date",
                "Folder Path",
                "Permission Type",
                "Role",
                "Email/Domain",
                "File ID",
                "Link",
            ]
        )

        page_token = None
        while True:
            try:
                results = (
                    service.files()
                    .list(
                        fields="nextPageToken, files(id, name, webViewLink, driveId, parents, modifiedTime)",
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                        pageSize=100,
                        pageToken=page_token,
                    )
                    .execute()
                )
            except Exception as e:
                print(f"Error listing files: {e}")
                break

            for item in results.get("files", []):
                file_id = item.get("id")
                drive_id = item.get("driveId")

                # 1. Resolve Shared Drive Name
                if drive_id and drive_id not in drive_names:
                    try:
                        d_info = service.drives().get(driveId=drive_id).execute()
                        drive_names[drive_id] = d_info.get("name")
                    except Exception:
                        drive_names[drive_id] = "Unknown/Private"

                current_drive_name = drive_names.get(drive_id, "My Drive")

                # 2. Fetch Path (Optional: can slow down significantly)
                parent_id = item.get("parents")[0] if item.get("parents") else None
                folder_path = get_full_path(service, parent_id) if parent_id else "Root"

                # 3. Fetch Permissions
                try:
                    perms = (
                        service.permissions()
                        .list(
                            fileId=file_id,
                            supportsAllDrives=True,
                            fields="permissions(type, role, emailAddress, domain)",
                        )
                        .execute()
                        .get("permissions", [])
                    )
                except Exception:
                    writer.writerow(
                        [
                            "UNKNOWN",
                            current_drive_name,
                            item.get("name"),
                            item.get("modifiedTime"),
                            folder_path,
                            "ACCESS_DENIED",
                            "N/A",
                            "N/A",
                            file_id,
                            item.get("webViewLink"),
                        ]
                    )
                    continue

                for p in perms:
                    email = p.get("emailAddress", p.get("domain", "Anyone with Link")).lower()
                    is_internal = INTERNAL_DOMAIN in email

                    # FILTER: Skip internal staff on Customer drives to reduce noise
                    if "Customers" in current_drive_name and is_internal:
                        continue

                    is_external = "TRUE" if (not is_internal or p.get("type") == "anyone") else "FALSE"

                    writer.writerow(
                        [
                            is_external,
                            current_drive_name,
                            item.get("name"),
                            item.get("modifiedTime"),
                            folder_path,
                            p.get("type"),
                            p.get("role"),
                            email,
                            file_id,
                            item.get("webViewLink"),
                        ]
                    )

            # 4. Flush buffer to prevent empty file on crash
            f.flush()
            print(f"Processed a page... Cached Paths: {len(folder_path_cache)}")

            page_token = results.get("nextPageToken")
            if not page_token:
                break


if __name__ == "__main__":
    run_verification_audit()
    print("Verification audit complete.")
