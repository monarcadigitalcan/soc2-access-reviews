#!/usr/bin/env python3
"""
CLI entry point for running access review scans.

Usage:
    # Scan both platforms
    python cli.py --all

    # Scan only Jira
    python cli.py --jira

    # Scan only Slack
    python cli.py --slack

    # Scan and upload to GCS
    python cli.py --all --upload

    # Save to a specific local directory
    python cli.py --all --output-dir /path/to/output

Environment:
    GCP_PROJECT_ID       - GCP project for Secret Manager
    GCS_BUCKET_NAME      - GCS bucket for CSV uploads
    JIRA_SITE_URL        - Jira Cloud URL (e.g. https://acme.atlassian.net)
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("access-review")


def run_jira_scan(output_dir: str, upload: bool = False) -> str:
    """Run Jira scan and save CSV. Returns the local file path."""
    from scanners.jira_scanner import JiraScanner

    scanner = JiraScanner()
    df = scanner.scan()

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"jira_access_review_{date_str}.csv"
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    logger.info(f"Jira scan saved to {filepath} ({len(df)} rows)")

    if upload:
        from scanners.config import upload_csv_to_gcs

        gcs_uri = upload_csv_to_gcs(filepath, "jira")
        logger.info(f"Uploaded to {gcs_uri}")

    return filepath


def run_slack_scan(output_dir: str, upload: bool = False) -> str:
    """Run Slack scan and save CSV. Returns the local file path."""
    from scanners.slack_scanner import SlackScanner

    scanner = SlackScanner()
    df = scanner.scan()

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"slack_access_review_{date_str}.csv"
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    logger.info(f"Slack scan saved to {filepath} ({len(df)} rows)")

    if upload:
        from scanners.config import upload_csv_to_gcs

        gcs_uri = upload_csv_to_gcs(filepath, "slack")
        logger.info(f"Uploaded to {gcs_uri}")

    return filepath


def run_jira_revoke(csv_path: str, output_dir: str, dry_run: bool = False) -> str:
    """Process a reviewed Jira CSV and revoke OFFBOARD rows. Returns output file path."""
    import pandas as pd
    from scanners.jira_revoker import JiraRevoker

    df = pd.read_csv(csv_path)
    # Ensure string columns aren't inferred as float when empty
    for col in ["revoke_status", "revoke_date", "reviewer_notes"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    revoker = JiraRevoker()

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()

    success_count = 0
    fail_count = 0
    skip_count = 0

    for idx, row in df.iterrows():
        if row["revoke_status"] != "OFFBOARD":
            skip_count += 1
            continue

        status, detail = revoker.revoke_row(row.to_dict(), dry_run=dry_run)
        df.at[idx, "revoke_status"] = status
        df.at[idx, "revoke_date"] = now_iso
        if status == "failed":
            df.at[idx, "reviewer_notes"] = detail
            fail_count += 1
        else:
            success_count += 1

    prefix = "dryrun_" if dry_run else ""
    out_path = os.path.join(output_dir, f"{prefix}jira_revoke_results_{date_str}.csv")
    df.to_csv(out_path, index=False)

    logger.info(f"Jira revoke complete: {success_count} success, {fail_count} failed, {skip_count} skipped")
    logger.info(f"Results written to {out_path}")
    return out_path


def run_slack_revoke(csv_path: str, output_dir: str, dry_run: bool = False) -> str:
    """Process a reviewed Slack CSV and revoke OFFBOARD rows. Returns output file path."""
    import pandas as pd
    from scanners.slack_revoker import SlackRevoker

    df = pd.read_csv(csv_path)
    for col in ["revoke_status", "revoke_date", "reviewer_notes"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    revoker = SlackRevoker()

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()

    success_count = 0
    fail_count = 0
    skip_count = 0

    for idx, row in df.iterrows():
        if row["revoke_status"] != "OFFBOARD":
            skip_count += 1
            continue

        status, detail = revoker.revoke_row(row.to_dict(), dry_run=dry_run)
        df.at[idx, "revoke_status"] = status
        df.at[idx, "revoke_date"] = now_iso
        if status == "failed":
            df.at[idx, "reviewer_notes"] = detail
            fail_count += 1
        else:
            success_count += 1

    prefix = "dryrun_" if dry_run else ""
    out_path = os.path.join(output_dir, f"{prefix}slack_revoke_results_{date_str}.csv")
    df.to_csv(out_path, index=False)

    logger.info(f"Slack revoke complete: {success_count} success, {fail_count} failed, {skip_count} skipped")
    logger.info(f"Results written to {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Jira & Slack Access Review Scanner & Revoker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    sub = parser.add_subparsers(dest="command")

    # --- scan subcommand ---
    scan_parser = sub.add_parser("scan", help="Run access scans")
    scan_parser.add_argument("--jira", action="store_true", help="Run Jira scan")
    scan_parser.add_argument("--slack", action="store_true", help="Run Slack scan")
    scan_parser.add_argument("--all", action="store_true", help="Run all scans")
    scan_parser.add_argument("--upload", action="store_true", help="Upload CSVs to GCS bucket")
    scan_parser.add_argument(
        "--output-dir",
        default="./output",
        help="Local directory for CSV output (default: ./output)",
    )

    # --- revoke subcommand ---
    revoke_parser = sub.add_parser("revoke", help="Revoke access from reviewed CSVs")
    revoke_parser.add_argument("csv", help="Path to reviewed CSV with revoke_status column")
    revoke_parser.add_argument("--platform", required=True, choices=["jira", "slack"], help="Platform to revoke from")
    revoke_parser.add_argument("--dry-run", action="store_true", help="Preview revocations without making changes")
    revoke_parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory for revoke results CSV (default: ./output)",
    )

    args = parser.parse_args()

    if args.command is None:
        # Backwards compat: if no subcommand, check for old-style flags
        parser.print_help()
        sys.exit(1)

    if args.command == "scan":
        if not (args.jira or args.slack or args.all):
            scan_parser.error("Specify --jira, --slack, or --all")

        os.makedirs(args.output_dir, exist_ok=True)
        results = []

        if args.jira or args.all:
            try:
                path = run_jira_scan(args.output_dir, upload=args.upload)
                results.append(("jira", path, "OK"))
            except Exception as e:
                logger.error(f"Jira scan failed: {e}")
                results.append(("jira", "", f"FAILED: {e}"))

        if args.slack or args.all:
            try:
                path = run_slack_scan(args.output_dir, upload=args.upload)
                results.append(("slack", path, "OK"))
            except Exception as e:
                logger.error(f"Slack scan failed: {e}")
                results.append(("slack", "", f"FAILED: {e}"))

        print("\n" + "=" * 60)
        print("ACCESS REVIEW SCAN SUMMARY")
        print("=" * 60)
        for platform, path, status in results:
            print(f"  {platform:<10} {status:<10} {path}")
        print("=" * 60)

        if any(s != "OK" for _, _, s in results):
            sys.exit(1)

    elif args.command == "revoke":
        if not os.path.isfile(args.csv):
            print(f"Error: file not found: {args.csv}")
            sys.exit(1)

        os.makedirs(args.output_dir, exist_ok=True)

        if args.dry_run:
            logger.info("=== DRY RUN MODE — no changes will be made ===")

        if args.platform == "jira":
            path = run_jira_revoke(args.csv, args.output_dir, dry_run=args.dry_run)
        elif args.platform == "slack":
            path = run_slack_revoke(args.csv, args.output_dir, dry_run=args.dry_run)

        print(f"\nResults written to: {path}")


if __name__ == "__main__":
    main()
