import csv
import os
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIGURATION ===
SERVICE_ACCOUNT_FILE = "service_account.json"
DELEGATED_EMAIL = os.getenv("DELEGATED_EMAIL", "reviewer@acme.example.com")
INPUT_CSV = "input/revoke_external.csv"
EVIDENCE_CSV = "output/evidence_external_revoked.csv"
SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("drive", "v3", credentials=creds.with_subject(DELEGATED_EMAIL))


def revoke_external_access():
    print(f"Loading targets from: {INPUT_CSV}", flush=True)
    print(f"Evidence will be saved to: {EVIDENCE_CSV}", flush=True)

    service = get_drive_service()

    with (
        open(INPUT_CSV, encoding="utf-8") as infile,
        open(EVIDENCE_CSV, mode="w", newline="", encoding="utf-8") as outfile,
    ):
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(
            outfile,
            fieldnames=[
                "Timestamp",
                "File Name",
                "File ID",
                "Email/Domain",
                "Permission Type",
                "Role",
                "Action",
                "Reason",
            ],
        )
        writer.writeheader()
        outfile.flush()

        stats = {"revoked": 0, "skipped": 0, "errors": 0, "total": 0}

        for row in reader:
            stats["total"] += 1
            file_id = row.get("File ID", "").strip()
            file_name = row.get("File Name", "").strip()
            email_domain = row.get("Email/Domain", "").strip().lower()
            perm_type = row.get("Permission Type", "").strip()
            role = row.get("Role", "").strip()
            remove = row.get("REMOVE Y/N", "").strip().upper()

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Skip rows not marked for removal
            if remove != "Y":
                stats["skipped"] += 1
                writer.writerow(
                    {
                        "Timestamp": timestamp,
                        "File Name": file_name,
                        "File ID": file_id,
                        "Email/Domain": email_domain,
                        "Permission Type": perm_type,
                        "Role": role,
                        "Action": "SKIPPED",
                        "Reason": "Not marked for removal",
                    }
                )
                outfile.flush()
                continue

            # Skip ACCESS_DENIED — we can't manage these
            if perm_type == "ACCESS_DENIED":
                stats["skipped"] += 1
                writer.writerow(
                    {
                        "Timestamp": timestamp,
                        "File Name": file_name,
                        "File ID": file_id,
                        "Email/Domain": email_domain,
                        "Permission Type": perm_type,
                        "Role": role,
                        "Action": "SKIPPED",
                        "Reason": "ACCESS_DENIED — cannot read permissions",
                    }
                )
                outfile.flush()
                continue

            # Skip owner permissions — Google won't allow deletion
            if role == "owner":
                stats["skipped"] += 1
                writer.writerow(
                    {
                        "Timestamp": timestamp,
                        "File Name": file_name,
                        "File ID": file_id,
                        "Email/Domain": email_domain,
                        "Permission Type": perm_type,
                        "Role": role,
                        "Action": "SKIPPED",
                        "Reason": "Owner permission — cannot be revoked via API",
                    }
                )
                outfile.flush()
                continue

            if not file_id:
                stats["skipped"] += 1
                writer.writerow(
                    {
                        "Timestamp": timestamp,
                        "File Name": file_name,
                        "File ID": "",
                        "Email/Domain": email_domain,
                        "Permission Type": perm_type,
                        "Role": role,
                        "Action": "SKIPPED",
                        "Reason": "Missing File ID",
                    }
                )
                outfile.flush()
                continue

            # Fetch active permissions and find the matching one
            try:
                results = (
                    service.permissions()
                    .list(fileId=file_id, fields="permissions(id, type, emailAddress, domain)", supportsAllDrives=True)
                    .execute()
                )

                perm_id_to_delete = None
                for perm in results.get("permissions", []):
                    # Match by type
                    if perm_type == "anyone" and perm.get("type") == "anyone":
                        perm_id_to_delete = perm.get("id")
                        break
                    elif perm_type == "domain" and perm.get("type") == "domain":
                        if perm.get("domain", "").lower() == email_domain:
                            perm_id_to_delete = perm.get("id")
                            break
                    elif perm_type == "user" and perm.get("type") == "user":
                        if perm.get("emailAddress", "").lower() == email_domain:
                            perm_id_to_delete = perm.get("id")
                            break
                    elif perm_type == "group" and perm.get("type") == "group":
                        if perm.get("emailAddress", "").lower() == email_domain:
                            perm_id_to_delete = perm.get("id")
                            break

                if not perm_id_to_delete:
                    stats["skipped"] += 1
                    writer.writerow(
                        {
                            "Timestamp": timestamp,
                            "File Name": file_name,
                            "File ID": file_id,
                            "Email/Domain": email_domain,
                            "Permission Type": perm_type,
                            "Role": role,
                            "Action": "SKIPPED",
                            "Reason": "Permission not found — already removed",
                        }
                    )
                    outfile.flush()
                    continue

                # Execute deletion
                service.permissions().delete(
                    fileId=file_id, permissionId=perm_id_to_delete, supportsAllDrives=True
                ).execute()

                stats["revoked"] += 1
                writer.writerow(
                    {
                        "Timestamp": timestamp,
                        "File Name": file_name,
                        "File ID": file_id,
                        "Email/Domain": email_domain,
                        "Permission Type": perm_type,
                        "Role": role,
                        "Action": "REVOKED",
                        "Reason": "",
                    }
                )
                outfile.flush()
                print(f"[{timestamp}] REVOKED {perm_type}:{email_domain} from {file_name}", flush=True)

            except Exception as e:
                stats["errors"] += 1
                writer.writerow(
                    {
                        "Timestamp": timestamp,
                        "File Name": file_name,
                        "File ID": file_id,
                        "Email/Domain": email_domain,
                        "Permission Type": perm_type,
                        "Role": role,
                        "Action": "ERROR",
                        "Reason": str(e),
                    }
                )
                outfile.flush()
                print(f"[{timestamp}] ERROR {file_name}: {e}", flush=True)

            # Progress every 50 rows
            if stats["total"] % 50 == 0:
                print(
                    f"[PROGRESS] {stats['total']}/891 processed | {stats['revoked']} revoked | {stats['skipped']} skipped | {stats['errors']} errors",
                    flush=True,
                )

    print("\n=== COMPLETE ===", flush=True)
    print(f"Total processed: {stats['total']}", flush=True)
    print(f"Revoked: {stats['revoked']}", flush=True)
    print(f"Skipped: {stats['skipped']}", flush=True)
    print(f"Errors: {stats['errors']}", flush=True)


if __name__ == "__main__":
    revoke_external_access()
