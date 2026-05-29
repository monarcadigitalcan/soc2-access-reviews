import os
import csv
import sys
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIGURATION ===
SERVICE_ACCOUNT_FILE = 'service_account.json'
DELEGATED_EMAIL = os.getenv('DELEGATED_EMAIL', 'reviewer@acme.example.com')
INPUT_CSV = 'input/review_stale_external_access.csv'
SOURCES_CSV = 'output/traced_stale_sources.csv'
EVIDENCE_CSV = 'output/evidence_stale_revoked.csv'
SKIPPED_CSV = 'output/stale_skipped.csv'
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds.with_subject(DELEGATED_EMAIL))

def phase1_dedupe_and_sample():
    """Deduplicate: pick one sample file per unique email+permission_type combo to trace."""
    print("=== PHASE 1a: DEDUPLICATING INPUT ===", flush=True)

    samples = {}  # key: (email, perm_type) -> one sample row
    skipped = []
    total = 0

    with open(INPUT_CSV, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            file_id = row.get('File ID', '').strip()
            email = row.get('Email/Domain', '').strip().lower()
            perm_type = row.get('Permission Type', '').strip()
            role = row.get('Role', '').strip()

            # Skip owners
            if role == 'owner':
                skipped.append(row)
                continue

            if not file_id or not email:
                skipped.append(row)
                continue

            key = (email, perm_type)
            if key not in samples:
                samples[key] = row

    print(f"Total input rows: {total}", flush=True)
    print(f"Unique email+type combos to trace: {len(samples)}", flush=True)
    print(f"Skipped (owner/invalid): {len(skipped)}", flush=True)

    # Save skipped for the record
    if skipped:
        with open(SKIPPED_CSV, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=skipped[0].keys())
            writer.writeheader()
            for r in skipped:
                writer.writerow(r)

    return samples

def phase1b_trace_sources(service, samples):
    """Trace each unique combo to its inheritance source."""
    print(f"\n=== PHASE 1b: TRACING {len(samples)} UNIQUE COMBOS ===", flush=True)

    sources = {}  # unique_key -> source info
    direct_perms = []  # direct permissions that need file-level revocation
    trace_errors = 0
    checked = 0

    for (email, perm_type), row in samples.items():
        checked += 1
        file_id = row.get('File ID', '').strip()

        try:
            results = service.permissions().list(
                fileId=file_id,
                fields="permissions(id, emailAddress, domain, type, permissionDetails)",
                supportsAllDrives=True
            ).execute()

            matched = False
            for perm in results.get('permissions', []):
                perm_email = perm.get('emailAddress', perm.get('domain', '')).lower()
                if perm_email != email:
                    continue

                details = perm.get('permissionDetails', [])
                if details and 'inheritedFrom' in details[0]:
                    source_id = details[0]['inheritedFrom']
                    perm_role = details[0].get('role', 'unknown')

                    try:
                        source_meta = service.files().get(
                            fileId=source_id, fields="name, mimeType", supportsAllDrives=True
                        ).execute()
                        source_name = source_meta.get('name')
                    except:
                        source_name = "Unknown/Inaccessible"

                    unique_key = f"{source_id}_{email}"
                    sources[unique_key] = {
                        'Source Name': source_name,
                        'Source ID': source_id,
                        'Target Email': email,
                        'Permission Type': perm.get('type'),
                        'Role': perm_role,
                        'Sample File ID': file_id
                    }
                else:
                    direct_perms.append({
                        'File ID': file_id,
                        'File Name': row.get('File Name', ''),
                        'Email': email,
                        'Permission Type': perm.get('type'),
                        'Role': row.get('Role', ''),
                        'Perm ID': perm.get('id')
                    })
                matched = True
                break

            if not matched:
                trace_errors += 1

        except Exception as e:
            trace_errors += 1

        if checked % 20 == 0:
            print(f"[TRACE] {checked}/{len(samples)} checked | {len(sources)} inherited sources | {len(direct_perms)} direct | {trace_errors} errors", flush=True)

    # Save sources
    with open(SOURCES_CSV, mode='w', newline='', encoding='utf-8') as f:
        fields = ['Source Name', 'Source ID', 'Target Email', 'Permission Type', 'Role', 'Sample File ID']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in sources.values():
            writer.writerow(row)

    print(f"\n[TRACE COMPLETE] {len(sources)} inherited sources + {len(direct_perms)} direct permissions from {checked} combos. Errors: {trace_errors}", flush=True)
    return sources, direct_perms

def phase2_revoke(service, sources, direct_perms):
    """Revoke inherited sources at folder level, then direct permissions at file level."""
    total_targets = len(sources) + len(direct_perms)
    print(f"\n=== PHASE 2: REVOKING {total_targets} PERMISSIONS ({len(sources)} inherited + {len(direct_perms)} direct) ===", flush=True)

    stats = {'revoked': 0, 'skipped': 0, 'errors': 0}

    with open(EVIDENCE_CSV, mode='w', newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=[
            'Timestamp', 'Type', 'Source/File Name', 'Source/File ID',
            'Target Email', 'Permission Type', 'Action', 'Reason'
        ])
        writer.writeheader()
        outfile.flush()

        # Revoke inherited sources
        for key, src in sources.items():
            source_id = src['Source ID']
            target_email = src['Target Email']
            source_name = src['Source Name']
            perm_type = src['Permission Type']
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
                    elif perm_type == 'group' and perm.get('type') == 'group':
                        if perm.get('emailAddress', '').lower() == target_email:
                            perm_id_to_delete = perm.get('id')
                            break
                    else:
                        if perm.get('emailAddress', '').lower() == target_email:
                            perm_id_to_delete = perm.get('id')
                            break

                if not perm_id_to_delete:
                    stats['skipped'] += 1
                    writer.writerow({
                        'Timestamp': timestamp, 'Type': 'INHERITED',
                        'Source/File Name': source_name, 'Source/File ID': source_id,
                        'Target Email': target_email, 'Permission Type': perm_type,
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
                    'Timestamp': timestamp, 'Type': 'INHERITED',
                    'Source/File Name': source_name, 'Source/File ID': source_id,
                    'Target Email': target_email, 'Permission Type': perm_type,
                    'Action': 'REVOKED', 'Reason': ''
                })
                outfile.flush()
                print(f"[{timestamp}] REVOKED inherited {perm_type}:{target_email} from folder '{source_name}'", flush=True)

            except Exception as e:
                stats['errors'] += 1
                writer.writerow({
                    'Timestamp': timestamp, 'Type': 'INHERITED',
                    'Source/File Name': source_name, 'Source/File ID': source_id,
                    'Target Email': target_email, 'Permission Type': perm_type,
                    'Action': 'ERROR', 'Reason': str(e)
                })
                outfile.flush()
                print(f"[{timestamp}] ERROR on folder '{source_name}': {e}", flush=True)

        # Revoke direct permissions
        for dp in direct_perms:
            file_id = dp['File ID']
            target_email = dp['Email']
            perm_id = dp['Perm ID']
            file_name = dp['File Name']
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            try:
                service.permissions().delete(
                    fileId=file_id,
                    permissionId=perm_id,
                    supportsAllDrives=True
                ).execute()

                stats['revoked'] += 1
                writer.writerow({
                    'Timestamp': timestamp, 'Type': 'DIRECT',
                    'Source/File Name': file_name, 'Source/File ID': file_id,
                    'Target Email': target_email, 'Permission Type': dp['Permission Type'],
                    'Action': 'REVOKED', 'Reason': ''
                })
                outfile.flush()
                print(f"[{timestamp}] REVOKED direct {target_email} from '{file_name}'", flush=True)

            except Exception as e:
                stats['errors'] += 1
                writer.writerow({
                    'Timestamp': timestamp, 'Type': 'DIRECT',
                    'Source/File Name': file_name, 'Source/File ID': file_id,
                    'Target Email': target_email, 'Permission Type': dp['Permission Type'],
                    'Action': 'ERROR', 'Reason': str(e)
                })
                outfile.flush()
                print(f"[{timestamp}] ERROR on '{file_name}': {e}", flush=True)

    print(f"\n=== COMPLETE ===", flush=True)
    print(f"Revoked: {stats['revoked']}", flush=True)
    print(f"Skipped: {stats['skipped']}", flush=True)
    print(f"Errors: {stats['errors']}", flush=True)

if __name__ == '__main__':
    service = get_drive_service()
    samples = phase1_dedupe_and_sample()
    sources, direct_perms = phase1b_trace_sources(service, samples)
    phase2_revoke(service, sources, direct_perms)
