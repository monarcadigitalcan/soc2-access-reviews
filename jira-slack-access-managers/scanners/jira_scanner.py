"""
Jira Cloud Access Scanner

Enumerates:
  - All projects and their roles (project-level access)
  - All groups and their members
  - User account status and last activity

Produces a pandas DataFrame conforming to csv_schema.COLUMNS.
"""

import logging

import pandas as pd
import requests

from .config import JIRA_SITE_URL, SECRET_JIRA_EMAIL, SECRET_JIRA_TOKEN, get_secret
from .csv_schema import normalize_dataframe

logger = logging.getLogger(__name__)


class JiraScanner:
    """Scans Jira Cloud for user access across projects and groups."""

    def __init__(self, site_url: str = None):
        self.site_url = (site_url or JIRA_SITE_URL).rstrip("/")
        if not self.site_url:
            raise ValueError("Jira site URL is required (e.g. https://yoursite.atlassian.net)")

        email = get_secret(SECRET_JIRA_EMAIL)
        token = get_secret(SECRET_JIRA_TOKEN)
        self.auth = (email, token)
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict = None) -> dict:
        """Make authenticated GET request to Jira REST API v3."""
        url = f"{self.site_url}/rest/api/3/{path}"
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _get_paginated(self, path: str, results_key: str = "values", params: dict = None) -> list:
        """Handle Jira's offset-based pagination."""
        params = params or {}
        params.setdefault("maxResults", 100)
        params.setdefault("startAt", 0)
        all_results = []

        while True:
            data = self._get(path, params=params)
            results = data.get(results_key, [])
            all_results.extend(results)

            total = data.get("total", len(all_results))
            if len(all_results) >= total:
                break
            params["startAt"] = len(all_results)

        return all_results

    # ----- Scanning methods ----- #

    def get_all_projects(self) -> list[dict]:
        """List all visible projects."""
        logger.info("Fetching all Jira projects...")
        projects = self._get_paginated("project/search")
        logger.info(f"Found {len(projects)} projects")
        return projects

    def get_project_roles(self, project_key: str) -> dict:
        """Get all role definitions for a project. Returns {role_name: role_url}."""
        data = self._get(f"project/{project_key}/role")
        return data  # dict of role_name -> URL

    def get_role_members(self, project_key: str, role_id: str) -> list[dict]:
        """Get all members (users + groups) assigned to a project role."""
        data = self._get(f"project/{project_key}/role/{role_id}")
        return data.get("actors", [])

    def get_all_groups(self) -> list[dict]:
        """List all groups in the Jira instance."""
        logger.info("Fetching all Jira groups...")
        data = self._get_paginated("group/bulk")
        logger.info(f"Found {len(data)} groups")
        return data

    def get_group_members(self, group_name: str) -> list[dict]:
        """List all members of a group."""
        return self._get_paginated(
            "group/member",
            results_key="values",
            params={"groupname": group_name},
        )

    # ----- Main scan ----- #

    def scan_project_roles(self) -> list[dict]:
        """Scan all projects and enumerate who has which role."""
        rows = []
        projects = self.get_all_projects()

        for project in projects:
            pkey = project["key"]
            pname = project.get("name", pkey)
            logger.info(f"Scanning project roles: {pkey}")

            try:
                roles = self.get_project_roles(pkey)
            except requests.HTTPError as e:
                logger.warning(f"Cannot read roles for {pkey}: {e}")
                continue

            for role_name, role_url in roles.items():
                # Extract role ID from URL (last segment)
                role_id = role_url.rstrip("/").split("/")[-1]

                try:
                    actors = self.get_role_members(pkey, role_id)
                except requests.HTTPError as e:
                    logger.warning(f"Cannot read role {role_name} for {pkey}: {e}")
                    continue

                for actor in actors:
                    actor_type = actor.get("type", "")
                    if actor_type == "atlassian-user-role-actor":
                        user = actor.get("actorUser", {})
                        rows.append(
                            {
                                "platform": "jira",
                                "resource_type": "project",
                                "resource_name": f"{pkey} - {pname}",
                                "resource_id": pkey,
                                "user_email": user.get("emailAddress", ""),
                                "user_display_name": actor.get("displayName", ""),
                                "user_id": user.get("accountId", ""),
                                "role": role_name,
                                "role_id": role_id,
                                "last_active": "",  # not available per-project
                                "granted_date": "",
                            }
                        )
                    elif actor_type == "atlassian-group-role-actor":
                        # Group assigned to role — we note the group, members enumerated separately
                        rows.append(
                            {
                                "platform": "jira",
                                "resource_type": "project_group_role",
                                "resource_name": f"{pkey} - {pname}",
                                "resource_id": pkey,
                                "user_email": "",
                                "user_display_name": f"[Group] {actor.get('displayName', '')}",
                                "user_id": actor.get("name", ""),
                                "role": role_name,
                                "role_id": role_id,
                                "last_active": "",
                                "granted_date": "",
                            }
                        )

        logger.info(f"Project role scan complete: {len(rows)} entries")
        return rows

    def scan_groups(self) -> list[dict]:
        """Scan all groups and their members."""
        rows = []
        groups = self.get_all_groups()

        for group in groups:
            gname = group.get("name", "")
            gid = group.get("groupId", "")
            logger.info(f"Scanning group: {gname}")

            try:
                members = self.get_group_members(gname)
            except requests.HTTPError as e:
                logger.warning(f"Cannot read members for group {gname}: {e}")
                continue

            for member in members:
                rows.append(
                    {
                        "platform": "jira",
                        "resource_type": "group",
                        "resource_name": gname,
                        "resource_id": gid,
                        "user_email": member.get("emailAddress", ""),
                        "user_display_name": member.get("displayName", ""),
                        "user_id": member.get("accountId", ""),
                        "role": "member",
                        "last_active": member.get("lastActive", ""),
                        "granted_date": "",
                    }
                )

        logger.info(f"Group scan complete: {len(rows)} entries")
        return rows

    def scan(self) -> pd.DataFrame:
        """
        Run the full Jira access scan.
        Returns a normalized DataFrame ready for CSV export.
        """
        logger.info("Starting full Jira access scan...")
        rows = []
        rows.extend(self.scan_project_roles())
        rows.extend(self.scan_groups())

        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame(columns=["platform"])  # ensure normalize works

        df = normalize_dataframe(df)

        # Mark departed employees (Phase 2)
        from .config import get_departed_employees

        departed = get_departed_employees()
        if departed:
            df.loc[df["user_email"].isin(departed), "departed"] = True

        logger.info(f"Jira scan complete: {len(df)} total rows")
        return df
