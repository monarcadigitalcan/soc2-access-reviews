"""
Jira Access Revoker

Reads a reviewed CSV (with revoke_status=OFFBOARD) and removes access
for each flagged row via the Jira REST API v3.

Handles three resource_type values:
  - group:              remove user from group
  - project:            remove user from project role
  - project_group_role: remove group from project role
"""

import logging
import requests
from datetime import datetime, timezone

from .config import get_secret, SECRET_JIRA_TOKEN, SECRET_JIRA_EMAIL, JIRA_SITE_URL

logger = logging.getLogger(__name__)


class JiraRevoker:
    """Revokes Jira access based on a reviewed CSV."""

    def __init__(self, site_url: str = None):
        self.site_url = (site_url or JIRA_SITE_URL).rstrip("/")
        if not self.site_url:
            raise ValueError("Jira site URL is required")

        email = get_secret(SECRET_JIRA_EMAIL)
        token = get_secret(SECRET_JIRA_TOKEN)
        self.session = requests.Session()
        self.session.auth = (email, token)
        self.session.headers.update({"Accept": "application/json"})

        # Cache: project_key -> {role_name: role_id}
        self._role_cache: dict[str, dict[str, str]] = {}

    def _get_role_id(self, project_key: str, role_name: str) -> str | None:
        """Resolve a role name to its numeric ID for a project."""
        if project_key not in self._role_cache:
            url = f"{self.site_url}/rest/api/3/project/{project_key}/role"
            resp = self.session.get(url)
            if not resp.ok:
                logger.error(f"Cannot fetch roles for {project_key}: {resp.status_code} {resp.text[:200]}")
                return None
            roles = resp.json()
            self._role_cache[project_key] = {
                name: role_url.rstrip("/").split("/")[-1]
                for name, role_url in roles.items()
            }

        role_id = self._role_cache[project_key].get(role_name)
        if not role_id:
            logger.warning(f"Role '{role_name}' not found in project {project_key}. "
                           f"Available: {list(self._role_cache[project_key].keys())}")
        return role_id

    def revoke_group_membership(self, group_id: str, account_id: str, dry_run: bool = False) -> tuple[bool, str]:
        """Remove a user from a Jira group."""
        url = f"{self.site_url}/rest/api/3/group/user"
        params = {"groupId": group_id, "accountId": account_id}

        if dry_run:
            logger.info(f"[DRY RUN] Would remove user {account_id} from group {group_id}")
            return True, "dry_run"

        resp = self.session.delete(url, params=params)
        if resp.ok:
            logger.info(f"Removed user {account_id} from group {group_id}")
            return True, "success"
        else:
            msg = f"{resp.status_code}: {resp.text[:200]}"
            logger.error(f"Failed to remove user {account_id} from group {group_id}: {msg}")
            return False, msg

    def revoke_project_role_user(self, project_key: str, role_name: str,
                                 account_id: str, dry_run: bool = False) -> tuple[bool, str]:
        """Remove a user from a project role."""
        role_id = self._get_role_id(project_key, role_name)
        if not role_id:
            return False, f"role '{role_name}' not found in project {project_key}"

        url = f"{self.site_url}/rest/api/3/project/{project_key}/role/{role_id}"
        params = {"user": account_id}

        if dry_run:
            logger.info(f"[DRY RUN] Would remove user {account_id} from {project_key} role {role_name} (id={role_id})")
            return True, "dry_run"

        resp = self.session.delete(url, params=params)
        if resp.ok:
            logger.info(f"Removed user {account_id} from {project_key} role {role_name}")
            return True, "success"
        else:
            msg = f"{resp.status_code}: {resp.text[:200]}"
            logger.error(f"Failed to remove user {account_id} from {project_key} role {role_name}: {msg}")
            return False, msg

    def revoke_project_role_group(self, project_key: str, role_name: str,
                                  group_name: str, dry_run: bool = False) -> tuple[bool, str]:
        """Remove a group from a project role."""
        role_id = self._get_role_id(project_key, role_name)
        if not role_id:
            return False, f"role '{role_name}' not found in project {project_key}"

        url = f"{self.site_url}/rest/api/3/project/{project_key}/role/{role_id}"
        params = {"group": group_name}

        if dry_run:
            logger.info(f"[DRY RUN] Would remove group '{group_name}' from {project_key} role {role_name} (id={role_id})")
            return True, "dry_run"

        resp = self.session.delete(url, params=params)
        if resp.ok:
            logger.info(f"Removed group '{group_name}' from {project_key} role {role_name}")
            return True, "success"
        else:
            msg = f"{resp.status_code}: {resp.text[:200]}"
            logger.error(f"Failed to remove group '{group_name}' from {project_key} role {role_name}: {msg}")
            return False, msg

    def revoke_row(self, row: dict, dry_run: bool = False) -> tuple[str, str]:
        """
        Revoke access for a single CSV row.
        Returns (revoke_status, error_detail).
        """
        resource_type = row["resource_type"]
        project_key = row["resource_id"]
        role_name = row["role"]
        user_id = row["user_id"]

        if resource_type == "group":
            group_id = row["resource_id"]  # resource_id is the group UUID
            ok, detail = self.revoke_group_membership(group_id, user_id, dry_run=dry_run)
        elif resource_type == "project":
            ok, detail = self.revoke_project_role_user(project_key, role_name, user_id, dry_run=dry_run)
        elif resource_type == "project_group_role":
            group_name = user_id  # for group-role entries, user_id holds the group name
            ok, detail = self.revoke_project_role_group(project_key, role_name, group_name, dry_run=dry_run)
        else:
            return "skipped", f"unknown resource_type: {resource_type}"

        status = "success" if ok else "failed"
        if dry_run and ok:
            status = "dry_run"
        return status, detail
