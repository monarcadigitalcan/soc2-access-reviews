import os
import csv
import sys
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIGURATION ===
SERVICE_ACCOUNT_FILE = 'service_account.json'
DELEGATED_EMAIL = os.getenv('DELEGATED_EMAIL', 'reviewer@acme.example.com')
INPUT_CSV = 'output/pending_inherited_permissions.csv'
SOURCES_CSV = 'output/traced_sources.csv'
EVIDENCE_CSV = 'output/evidence_inherited_revoked.csv'
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds.with_subject(DELEGATED_EMAIL))

def phase1_trace_sources(service):
    """Trace each inherited permission back to its source folder/drive."""
    print("=== PHASE 1: TRACING INHERITANCE SOURCES ===", flush=True)

    sources = {}  # unique_key -> source info
    trace_errors = 0

    with open(INPUT_CSV, mode='r', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        total = 0

        for row in reader:
            total += 1
            file_id = row.get('File ID', '').strip()
            target_email = row.get('Email/Domain', '').strip().lower()

            if not file_id or not target_email:
                continue

            try:
                results = service.permissions().list(
                    fileId=file_id,
                    fields="permissions(id, emailAddress, domain, type, permissionDetails)",
                    supportsAllDrives=True
                ).execute()

                for perm in results.get('permissions', []):
                    perm_email = perm.get('emailAddress', perm.get('domain', '')).lower()
                    if perm_email != target_email:
                        continue

                    details = perm.get('permissionDetails', [])
                    if details and 'inheritedFrom' in details[0]:
                        source_id = details[0]['inheritedFrom']
                        perm_role = details[0].get('role', 'unknown')

                        # Fetch source folder name
                        try:
                            source_meta = service.files().get(
                                fileId=source_id, fields="name, mimeType", supportsAllDrives=True
                            ).execute()
                            source_name = source_meta.get('name')
                        except:
                            source_name = "Unknown/Inaccessible"

                        unique_key = f"{source_id}_{target_email}"
                        sources[unique_key] = {
                            'Source Name': source_name,
                            'Source ID': source_id,
                            'Target Email': target_email,
                            'Permission Type': perm.get('type'),
                            'Role': perm_role,
                            'Sample File ID': file_id
                        }
                    else:
                        # Direct permission that failed for another reason
                        unique_key = f"direct_{file_id}_{target_email}"
                        sources[unique_key] = {
                            'Source Name': '[DIRECT - not inherited]',
                            'Source ID': file_id,
                            'Target Email': target_email,
                            'Permission Type': perm.get('type'),
                            'Role': 'direct',
                            'Sample File ID': file_id
                        }
                    break

            except Exception as e:
                trace_errors += 1

            if total % 50 == 0:
                print(f"[TRACE] {total}/603 checked | {len(sources)} unique sources found | {trace_errors} errors", flush=True)

    # Write sources for reference
    with open(SOURCES_CSV, mode='w', newline='', encoding='utf-8') as outfile:
        fields = ['Source Name', 'Source ID', 'Target Email', 'Permission Type', 'Role', 'Sample File ID']
        writer = csv.DictWriter(outfile, fieldnames=fields)
        writer.writeheader()
        for row in sources.values():
            writer.writerow(row)

    print(f"\n[TRACE COMPLETE] {len(sources)} unique source/email combos found from {total} files. Saved to {SOURCES_CSV}", flush=True)
    print(f"[TRACE ERRORS] {trace_errors}", flush=True)
    return sources

def phase2_revoke_sources(service, sources):
    """Revoke permissions at the source folder/drive level."""
    print(f"\n=== PHASE 2: REVOKING {len(sources)} SOURCE PERMISSIONS ===", flush=True)

    stats = {'revoked': 0, 'skipped': 0, 'errors': 0}

    with open(EVIDENCE_CSV, mode='w', newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=[
            'Timestamp', 'Source Name', 'Source ID', 'Target Email',
            'Permission Type', 'Action', 'Reason'
        ])
        writer.writeheader()
        outfile.flush()

        for key, src in sources.items():
            source_id = src['Source ID']
            target_email = src['Target Email']
            source_name = src['Source Name']
            perm_type = src['Permission Type']
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if src['Role'] == 'direct':
                stats['skipped'] += 1
                writer.writerow({
                    'Timestamp': timestamp, 'Source Name': source_name,
                    'Source ID': source_id, 'Target Email': target_email,
                    'Permission Type': perm_type,
                    'Action': 'SKIPPED', 'Reason': 'Direct permission — retry individually'
                })
                outfile.flush()
                continue

            try:
                results = service.permissions().list(
                    fileId=source_id,
                    fields="permissions(id, emailAddress, domain, type)",
                    supportsAllDrives=True
                ).execute()

                perm_id_to_delete = None
                for perm in results.get('permissions', []):
                    if perm_type == 'anyone' and perm.get('type') == 'anyone':
                        perm_id_to_delete = perm.get('id')
                        break
                    elif perm_type == 'domain' and perm.get('type') == 'domain':
                        if perm.get('domain', '').lower() == target_email:
                            perm_id_to_delete = perm.get('id')
                            break
                    else:
                        if perm.get('emailAddress', '').lower() == target_email:
                            perm_id_to_delete = perm.get('id')
                            break

                if not perm_id_to_delete:
                    stats['skipped'] += 1
                    writer.writerow({
                        'Timestamp': timestamp, 'Source Name': source_name,
                        'Source ID': source_id, 'Target Email': target_email,
                        'Permission Type': perm_type,
                        'Action': 'SKIPPED', 'Reason': 'Permission not found — already removed'
                    })
                    outfile.flush()
                    continue

                service.permissions().delete(
                    fileId=source_id,
                    permissionId=perm_id_to_delete,
                    supportsAllDrives=True
                ).execute()

                stats['revoked'] += 1
                writer.writerow({
                    'Timestamp': timestamp, 'Source Name': source_name,
                    'Source ID': source_id, 'Target Email': target_email,
                    'Permission Type': perm_type,
                    'Action': 'REVOKED', 'Reason': ''
                })
                outfile.flush()
                print(f"[{timestamp}] REVOKED {target_email} from folder '{source_name}'", flush=True)

            except Exception as e:
                stats['errors'] += 1
                writer.writerow({
                    'Timestamp': timestamp, 'Source Name': source_name,
                    'Source ID': source_id, 'Target Email': target_email,
                    'Permission Type': perm_type,
                    'Action': 'ERROR', 'Reason': str(e)
                })
                outfile.flush()
                print(f"[{timestamp}] ERROR on '{source_name}': {e}", flush=True)

    print(f"\n=== COMPLETE ===", flush=True)
    print(f"Revoked: {stats['revoked']}", flush=True)
    print(f"Skipped: {stats['skipped']}", flush=True)
    print(f"Errors: {stats['errors']}", flush=True)

if __name__ == '__main__':
    service = get_drive_service()
    sources = phase1_trace_sources(service)
    phase2_revoke_sources(service, sources)
