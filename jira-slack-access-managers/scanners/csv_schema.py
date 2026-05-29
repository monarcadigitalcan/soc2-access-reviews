"""
Shared CSV schema definition for access review reports.
All scanners produce DataFrames with these columns.
"""

# Column order for output CSVs
COLUMNS = [
    "platform",
    "resource_type",
    "resource_name",
    "resource_id",
    "user_email",
    "user_display_name",
    "user_id",
    "role",
    "role_id",
    "last_active",
    "granted_date",
    "departed",
    "flagged",
    "reviewer_notes",
    "revoke_status",
    "revoke_date",
]

# Columns that scanners populate (the rest are filled by reviewers or revoke scripts)
SCANNER_COLUMNS = [
    "platform",
    "resource_type",
    "resource_name",
    "resource_id",
    "user_email",
    "user_display_name",
    "user_id",
    "role",
    "role_id",
    "last_active",
    "granted_date",
]

# Default values for reviewer/revoke columns
DEFAULTS = {
    "departed": False,
    "flagged": False,
    "reviewer_notes": "",
    "revoke_status": "pending",
    "revoke_date": "",
}


def normalize_dataframe(df):
    """Ensure a DataFrame has all required columns with defaults."""

    for col in COLUMNS:
        if col not in df.columns:
            df[col] = DEFAULTS.get(col, "")
    return df[COLUMNS]
