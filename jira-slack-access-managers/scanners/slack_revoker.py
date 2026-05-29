"""
Slack Access Revoker

Reads a reviewed CSV (with revoke_status=OFFBOARD) and removes access
for each flagged row via the Slack Web API.

Handles two resource_type values:
  - public_channel:  kick user from channel (conversations.kick)
  - workspace:       deactivate user account (admin.users.remove — Enterprise Grid only)

Required bot scopes: channels:manage, groups:write
"""

import logging
import time
import requests

from .config import get_secret, SECRET_SLACK_TOKEN

logger = logging.getLogger(__name__)

# Be conservative with rate limits — Slack Tier 3 methods allow ~50 req/min
RATE_LIMIT_DELAY = 1.2


class SlackRevoker:
    """Revokes Slack access based on a reviewed CSV."""

    def __init__(self):
        self.token = get_secret(SECRET_SLACK_TOKEN)
        self.base_url = "https://slack.com/api"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _api(self, method: str, data: dict) -> dict:
        """Call a Slack Web API method via POST."""
        url = f"{self.base_url}/{method}"
        resp = requests.post(url, headers=self.headers, data=data)
        resp.raise_for_status()
        result = resp.json()

        # Handle rate limiting
        if result.get("error") == "ratelimited":
            retry_after = int(resp.headers.get("Retry-After", 30))
            logger.warning(f"Rate limited on {method}, waiting {retry_after}s")
            time.sleep(retry_after)
            resp = requests.post(url, headers=self.headers, data=data)
            resp.raise_for_status()
            result = resp.json()

        return result

    def kick_from_channel(self, channel_id: str, user_id: str,
                          dry_run: bool = False) -> tuple[bool, str]:
        """Remove a user from a channel."""
        if dry_run:
            logger.info(f"[DRY RUN] Would kick {user_id} from channel {channel_id}")
            return True, "dry_run"

        result = self._api("conversations.kick", {
            "channel": channel_id,
            "user": user_id,
        })

        if result.get("ok"):
            logger.info(f"Kicked {user_id} from channel {channel_id}")
            return True, "success"
        else:
            error = result.get("error", "unknown")
            # Not-in-channel is a benign failure
            if error in ("not_in_channel", "user_not_found", "channel_not_found"):
                logger.info(f"Benign: {user_id} in {channel_id}: {error}")
                return False, error
            logger.error(f"Failed to kick {user_id} from {channel_id}: {error}")
            return False, error

    def deactivate_user(self, team_id: str, user_id: str,
                        dry_run: bool = False) -> tuple[bool, str]:
        """
        Deactivate a user from the workspace.
        Requires admin.users.remove scope (Enterprise Grid only).
        """
        if dry_run:
            logger.info(f"[DRY RUN] Would deactivate user {user_id} from workspace {team_id}")
            return True, "dry_run"

        result = self._api("admin.users.remove", {
            "team_id": team_id,
            "user_id": user_id,
        })

        if result.get("ok"):
            logger.info(f"Deactivated user {user_id} from workspace {team_id}")
            return True, "success"
        else:
            error = result.get("error", "unknown")
            logger.error(f"Failed to deactivate {user_id}: {error}")
            return False, error

    def revoke_row(self, row: dict, dry_run: bool = False) -> tuple[str, str]:
        """
        Revoke access for a single CSV row.
        Returns (revoke_status, error_detail).
        """
        resource_type = row["resource_type"]
        user_id = row["user_id"]

        if resource_type in ("public_channel", "private_channel"):
            channel_id = row["resource_id"]
            ok, detail = self.kick_from_channel(channel_id, user_id, dry_run=dry_run)
            if not dry_run:
                time.sleep(RATE_LIMIT_DELAY)
        elif resource_type == "workspace":
            team_id = row["resource_id"]
            ok, detail = self.deactivate_user(team_id, user_id, dry_run=dry_run)
            if not dry_run:
                time.sleep(RATE_LIMIT_DELAY)
        else:
            return "skipped", f"unknown resource_type: {resource_type}"

        status = "success" if ok else "failed"
        if dry_run and ok:
            status = "dry_run"
        return status, detail
