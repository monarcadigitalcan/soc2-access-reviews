import os
import csv
import datetime
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build

# === CONFIGURATION ===
SERVICE_ACCOUNT_FILE = 'service_account.json'
IMPERSONATED_USER = os.getenv('IMPERSONATED_USER', 'reviewer@acme.example.com') 
# Load emails from file
with open('input/emails_revoke.txt', 'r') as f:
    EMAILS_TO_REVOKE = [line.strip().lower() for line in f if line.strip()]
LOG_FILE = 'output/remediation_evidence.csv'
# MUST HAVE 'drive' (not readonly) scope
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds.with_subject(IMPERSONATED_USER))

def revoke_and_log():
    service = get_drive_service()
    
    # Open the log file to record evidence
    with open(LOG_FILE, mode='w', newline='', encoding='utf-8') as log_file:
        writer = csv.writer(log_file)
        writer.writerow(['Timestamp', 'Target Email', 'File Name', 'File ID', 'Status'])

        page_token = None
        while True:
            results = service.files().list(
                fields="nextPageToken, files(id, name)",
                supportsAllDrives=True, 
                includeItemsFromAllDrives=True,
                pageSize=100,
                pageToken=page_token
            ).execute()

            for file in results.get('files', []):
                try:
                    perms = service.permissions().list(
                        fileId=file['id'], 
                        supportsAllDrives=True, 
                        fields="permissions(id, emailAddress)"
                    ).execute().get('permissions', [])
                    
                    for p in perms:
                        email = p.get('emailAddress', '').lower()
                        if email in [e.lower() for e in EMAILS_TO_REVOKE]:
                            # Perform the deletion
                            service.permissions().delete(
                                fileId=file['id'], 
                                permissionId=p['id'], 
                                supportsAllDrives=True
                            ).execute()
                            
                            # Log the evidence
                            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            writer.writerow([timestamp, email, file['name'], file['id'], 'REMOVED'])
                            print(f"[{timestamp}] REMOVED {email} from {file['name']}")
                            
                except Exception as e:
                    continue # Likely insufficient permissions to manage this specific file

            page_token = results.get('nextPageToken')
            if not page_token: break

if __name__ == '__main__':
    print(f"Starting Revocation. Evidence will be saved to {LOG_FILE}...")
    revoke_and_log()
    print("Cleanup complete.")