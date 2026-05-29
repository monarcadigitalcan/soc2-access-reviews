import pandas as pd
from datetime import datetime, timedelta

# === CONFIGURATION ===
BEFORE_FILE = 'input/audit_Q1_2026_BEFORE.csv'
# AFTER_FILE = 'audit_Q1_2026_AFTER_CLEAN.csv'
STALE_DAYS_THRESHOLD = 180

def run_soc2_analysis():
    print("Loading audit data...")
    try:
        before_df = pd.read_csv(BEFORE_FILE)
#        after_df = pd.read_csv(AFTER_FILE)
    except FileNotFoundError as e:
        print(f"Error: {e}. Make sure both CSVs are in this directory.")
        return

    # ==========================================
    # FEATURE 1: THE DELTA ENGINE (REMEDIATION)
    # ==========================================
#    print("Running Delta Engine...")
    
    # We want to find permissions (File ID + Email combo) that exist in BEFORE, but NOT in AFTER.
    # We do a "Left Merge" and keep only the rows that didn't find a match in the After file.
#    delta_df = before_df.merge(
#        after_df[['File ID', 'Email/Domain']], # Only match on these two columns
#        on=['File ID', 'Email/Domain'], 
#        how='left', 
#        indicator=True
#    )
    
    # Filter for items that only existed in the 'left' (Before) dataset
#    remediated_df = delta_df[delta_df['_merge'] == 'left_only'].drop(columns=['_merge'])
    
    # Save the evidence
#    remediated_df.to_csv('evidence_remediated_access.csv', index=False)
#    print(f"-> Found {len(remediated_df)} revoked permissions. Saved to 'evidence_remediated_access.csv'")

    # ==========================================
    # FEATURE 2: STALE ACCESS DETECTION
    # ==========================================
    print(f"Running Stale Access Detection (> {STALE_DAYS_THRESHOLD} days)...")
    
    # Ensure there is a 'Modified Date' column (Assumes you added it to the audit script!)
    if 'Modified Date' in before_df.columns:
        # Convert Google's date string (e.g., 2024-08-15T10:00:00Z) to a real datetime object
        before_df['Modified Date'] = pd.to_datetime(before_df['Modified Date'], errors='coerce')
        
        # Calculate the cutoff date
        cutoff_date = datetime.now(tz=before_df['Modified Date'].dt.tz) - timedelta(days=STALE_DAYS_THRESHOLD)
        
        # Filter: External = TRUE AND Modified Date is older than cutoff
        stale_df = before_df[
            (before_df['Flagged External'].astype(str).str.upper() == 'TRUE') & 
            (before_df['Modified Date'] < cutoff_date)
        ]
        
        stale_df.to_csv('output/review_stale_external_access.csv', index=False)
        print(f"-> Found {len(stale_df)} stale external shares. Saved to 'output/review_stale_external_access.csv'")
    else:
        print("-> SKIPPED: 'Modified Date' column not found in the BEFORE CSV. Update your audit script!")

    print("\nAnalysis Complete! You are ready for the auditors.")

if __name__ == '__main__':
    run_soc2_analysis()