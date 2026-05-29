"""
Slack Workspace Access Scanner

Enumerates:
  - All workspace members and their account type / status
  - All channels (public + private if scopes allow) and their members
  - Channel-level membership mapping

Produces a pandas DataFrame conforming to csv_schema.COLUMNS.

Required Slack Bot Token scopes:
  users:read, users:read.email, channels:read, groups:read
  (channels:read and groups:read cover conversations.members access)
"""

import logging
import time
import pandas as pd
from typing import Optional
from .config import get_secret, SECRET_SLACK_TOKEN
from .csv_schema import normalize_dataframe

logger = logging.getLogger(__name__)

# Slack API rate limit: ~1 req/sec for Tier 2+ methods
RATE_LIMIT_DELAY = 1.1  # seconds between paginated calls


class SlackScanner:
    """Scans a Slack workspace for user access across channels."""

    def __init__(self):
        self.token = get_secret(SECRET_SLACK_TOKEN)
        self.base_url = "https://slack.com/api"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _api(self, method: str, params: dict = None) -> dict:
        """Call a Slack Web API method."""
        import requests

        url = f"{self.base_url}/{method}"
        resp = requests.get(url, headers=self.headers, params=params or {})
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            error = data.get("error", "unknown")
            logger.error(f"Slack API error on {method}: {error}")
            raise RuntimeError(f"Slack API error: {error}")
        return data

    def _api_paginated(self, method: str, results_key: str, params: dict = None) -> list:
        """Handle Slack's cursor-based pagination."""
        params = params or {}
        params.setdefault("limit", 200)
        all_results = []

        while True:
            data = self._api(method, params=params)
            results = data.get(results_key, [])
            all_results.extend(results)

            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
            params["cursor"] = cursor
            time.sleep(RATE_LIMIT_DELAY)  # respect rate limits

        return all_results

    # ----- Scanning methods ----- #

    def get_all_users(self) -> list[dict]:
        """List all workspace members."""
        logger.info("Fetching all Slack users...")
        users = self._api_paginated("users.list", "members")
        # Filter out bots and Slackbot
        real_users = [
            u for u in users
            if not u.get("is_bot") and u.get("id") != "USLACKBOT"
        ]
        logger.info(f"Found {len(real_users)} real users ({len(users)} total including bots)")
        return real_users

    def get_all_channels(self, include_private: bool = True) -> list[dict]:
        """List all channels (public, and private if scopes allow)."""
        logger.info("Fetching all Slack channels...")
        types = "public_channel,private_channel" if include_private else "public_channel"
        channels = self._api_paginated(
            "conversations.list",
            "channels",
            params={"types": types, "exclude_archived": "true"},
        )
        logger.info(f"Found {len(channels)} active channels")
        return channels

    def get_channel_members(self, channel_id: str) -> list[str]:
        """Get all member user IDs for a channel."""
        return self._api_paginated(
            "conversations.members",
            "members",
            params={"channel": channel_id},
        )

    # ----- Main scan ----- #

    def scan_workspace_users(self) -> list[dict]:
        """Scan all workspace users and their account status."""
        rows = []
        users = self.get_all_users()

        for user in users:
            profile = user.get("profile", {})
            # Determine role
            if user.get("is_owner"):
                role = "owner"
            elif user.get("is_admin"):
                role = "admin"
            elif user.get("is_ultra_restricted"):
                role = "single_channel_guest"
            elif user.get("is_restricted"):
                role = "multi_channel_guest"
            else:
                role = "member"

            status = "deactivated" if user.get("deleted") else "active"

            rows.append({
                "platform": "slack",
                "resource_type": "workspace",
                "resource_name": "workspace",
                "resource_id": user.get("team_id", ""),
                "user_email": profile.get("email", ""),
                "user_display_name": profile.get("real_name", user.get("name", "")),
                "user_id": user.get("id", ""),
                "role": f"{role} ({status})",
                "last_active": "",  # requires admin.users.list (Enterprise Grid)
                "granted_date": "",
            })

        logger.info(f"Workspace user scan complete: {len(rows)} entries")
        return rows

    def scan_channel_memberships(self) -> list[dict]:
        """Scan all channels and enumerate members."""
        rows = []
        users = self.get_all_users()
        user_lookup = {u["id"]: u for u in users}

        channels = self.get_all_channels()

        for channel in channels:
            ch_name = channel.get("name", "")
            ch_id = channel.get("id", "")
            ch_type = "private_channel" if channel.get("is_private") else "public_channel"
            logger.info(f"Scanning channel: #{ch_name} ({ch_type})")

            try:
                member_ids = self.get_channel_members(ch_id)
            except RuntimeError as e:
                logger.warning(f"Cannot read members for #{ch_name}: {e}")
                continue

            for uid in member_ids:
                # Skip Slack Connect external users (not in our workspace)
                if uid not in user_lookup:
                    continue
                user = user_lookup[uid]
                profile = user.get("profile", {})
                rows.append({
                    "platform": "slack",
                    "resource_type": ch_type,
                    "resource_name": f"#{ch_name}",
                    "resource_id": ch_id,
                    "user_email": profile.get("email", ""),
                    "user_display_name": profile.get("real_name", user.get("name", uid)),
                    "user_id": uid,
                    "role": "member",
                    "last_active": "",
                    "granted_date": "",
                })

            time.sleep(RATE_LIMIT_DELAY)  # be polite to Slack

        logger.info(f"Channel membership scan complete: {len(rows)} entries")
        return rows

    def scan(self) -> pd.DataFrame:
        """
        Run the full Slack access scan.
        Returns a normalized DataFrame ready for CSV export.
        """
        logger.info("Starting full Slack access scan...")
        rows = []
        rows.extend(self.scan_workspace_users())
        rows.extend(self.scan_channel_memberships())

        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame(columns=["platform"])

        df = normalize_dataframe(df)

        # Mark departed employees (Phase 2)
        from .config import get_departed_employees
        departed = get_departed_employees()
        if departed:
            df.loc[df["user_email"].isin(departed), "departed"] = True

        logger.info(f"Slack scan complete: {len(df)} total rows")
        return df
