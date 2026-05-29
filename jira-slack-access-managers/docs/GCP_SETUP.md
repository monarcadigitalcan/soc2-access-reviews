# GCP Setup Guide — Bucket + Secrets Provisioning

This guide walks you through setting up the GCP infrastructure for the access review scanners.

## Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- You have Owner or Editor role on the GCP project
- The GCP project already exists (same one used for GDrive review scripts)

## Step 0: Set your project

```bash
# Set your project ID — replace with your actual project
export PROJECT_ID="your-gcp-project-id"
gcloud config set project $PROJECT_ID
```

## Step 1: Enable required APIs

```bash
gcloud services enable secretmanager.googleapis.com
gcloud services enable storage.googleapis.com
```

## Step 2: Create the GCS bucket

```bash
# Choose a globally unique bucket name
export BUCKET_NAME="${PROJECT_ID}-compliance-reviews"

# Create the bucket (us-central1 or your preferred region)
gcloud storage buckets create gs://$BUCKET_NAME \
    --location=us-central1 \
    --uniform-bucket-level-access \
    --public-access-prevention

# Enable versioning for audit trail
gcloud storage buckets update gs://$BUCKET_NAME --versioning

# Set lifecycle rule: auto-delete after 365 days (adjust as needed)
cat > /tmp/lifecycle.json << 'LIFECYCLE'
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {"age": 365}
    }
  ]
}
LIFECYCLE
gcloud storage buckets update gs://$BUCKET_NAME --lifecycle-file=/tmp/lifecycle.json
```

## Step 3: Create secrets in Secret Manager

### 3a: Jira API Token

First, generate the token:
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Label it "access-review-scanner" (or similar)
4. Copy the token value

Then store it:

```bash
# Store the Jira API token
echo -n "YOUR_JIRA_API_TOKEN_HERE" | \
    gcloud secrets create jira-access-review-token \
    --data-file=- \
    --replication-policy=automatic

# Store the admin email used with the token
echo -n "reviewer@acme.example.com" | \
    gcloud secrets create jira-admin-email \
    --data-file=- \
    --replication-policy=automatic
```

### 3b: Slack Bot Token

First, create the Slack App:
1. Go to https://api.slack.com/apps → "Create New App" → "From scratch"
2. Name: "Access Review Scanner", pick your workspace
3. Go to "OAuth & Permissions" → "Scopes" → add Bot Token Scopes:
   - `users:read`
   - `users:read.email`
   - `channels:read`
   - `groups:read` (for private channels)
4. "Install to Workspace" → approve
5. Copy the "Bot User OAuth Token" (`xoxb-...`)

Then store it:

```bash
echo -n "xoxb-YOUR-SLACK-BOT-TOKEN" | \
    gcloud secrets create slack-access-review-bot-token \
    --data-file=- \
    --replication-policy=automatic
```

## Step 4: Grant the VM's service account access

```bash
# Find your VM's service account (check the VM details in Cloud Console,
# or use the default compute service account)
export SA_EMAIL="YOUR_VM_SERVICE_ACCOUNT@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant Secret Manager access
gcloud secrets add-iam-policy-binding jira-access-review-token \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding jira-admin-email \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding slack-access-review-bot-token \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor"

# Grant GCS write access
gcloud storage buckets add-iam-policy-binding gs://$BUCKET_NAME \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectAdmin"
```

## Step 5: Set environment variables on the VM

SSH into the VM and add to `.bashrc` or a systemd env file:

```bash
export GCP_PROJECT_ID="your-gcp-project-id"
export GCS_BUCKET_NAME="your-gcp-project-id-compliance-reviews"
export JIRA_SITE_URL="https://acme.atlassian.net"
```

## Step 6: Verify everything works

```bash
# On the VM, test secret access
gcloud secrets versions access latest --secret=jira-access-review-token

# Test GCS write
echo "test" > /tmp/test.txt
gcloud storage cp /tmp/test.txt gs://$BUCKET_NAME/test.txt
gcloud storage rm gs://$BUCKET_NAME/test.txt

# Run a scan
cd /path/to/jira-slack-access-managers
python cli.py --all --upload
```

## Troubleshooting

**"Permission denied" on secrets:**
- Verify the VM's service account has `secretAccessor` role
- Check: `gcloud secrets get-iam-policy jira-access-review-token`

**"403 Forbidden" on Jira API:**
- The API token is scoped to the generating user's permissions
- Ensure the token owner's Jira account has admin/browse access to all projects

**"missing_scope" on Slack API:**
- Reinstall the Slack app after adding scopes (scopes aren't applied until reinstall)
- Check installed scopes at: https://api.slack.com/apps → your app → OAuth & Permissions

**"Bucket not found":**
- Verify bucket name matches: `gcloud storage ls gs://$BUCKET_NAME`
