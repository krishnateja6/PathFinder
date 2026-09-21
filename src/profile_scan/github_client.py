"""GitHub API client for the Profile Scan feature: fetch a user's public,
non-fork repos and the completeness signals needed to score them.

Deliberately independent of src/ingestion/github_client.py — a small
amount of duplication (auth headers, error handling) is worth keeping
this feature genuinely separate from the repo-analysis pipeline, per
spec section 3E.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

API_BASE_URL = "https://api.github.com"
_TIMEOUT_SECONDS = 10.0
DEFAULT_LIMIT = 30


class ProfileScanError(Exception):
    """Base class for all profile-scan-related failures."""


class UserNotFoundError(ProfileScanError):
    pass


class RateLimitedError(ProfileScanError):
    pass


class NetworkError(ProfileScanError):
    pass


@dataclass(frozen=True)
class RepoSignals:
    name: str
    full_name: str
    stars: int
    forks: int
    open_issues: int
    days_since_last_push: int
    has_readme: bool
    has_license: bool
    has_ci: bool


class GitHubProfileClient(Protocol):
    def list_repo_signals(self, username: str, limit: int = DEFAULT_LIMIT) -> list[RepoSignals]: ...
    def get_readme_content(self, full_name: str) -> str | None: ...


def _auth_headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _is_rate_limited(status_code: int, body_text: str) -> bool:
    return status_code == 403 and "rate limit" in body_text.lower()


def _days_since(iso_timestamp: str) -> int:
    pushed = datetime.fromisoformat(iso_timestamp)
    return (datetime.now(UTC) - pushed).days


class RealGitHubProfileClient:
    """httpx-backed implementation. Uses a server-side GITHUB_TOKEN if set."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN")

    def _get_json(self, url: str):
        import httpx

        try:
            response = httpx.get(url, headers=_auth_headers(self._token), timeout=_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        if response.status_code == 404:
            return None
        if _is_rate_limited(response.status_code, response.text):
            raise RateLimitedError("GitHub API rate limit exceeded")
        response.raise_for_status()
        return response.json()

    def _path_exists(self, url: str) -> bool:
        return self._get_json(url) is not None

    def get_readme_content(self, full_name: str) -> str | None:
        """The repo's README as plain text, or None if it has none."""
        import httpx

        headers = _auth_headers(self._token)
        headers["Accept"] = "application/vnd.github.raw+json"
        try:
            response = httpx.get(f"{API_BASE_URL}/repos/{full_name}/readme", headers=headers, timeout=_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        if response.status_code == 404:
            return None
        if _is_rate_limited(response.status_code, response.text):
            raise RateLimitedError("GitHub API rate limit exceeded")
        response.raise_for_status()
        return response.text

    def list_repo_signals(self, username: str, limit: int = DEFAULT_LIMIT) -> list[RepoSignals]:
        repos = self._get_json(f"{API_BASE_URL}/users/{username}/repos?type=owner&per_page=100&sort=pushed")
        if repos is None:
            raise UserNotFoundError(f"GitHub user {username!r} not found")

        non_forks = [r for r in repos if not r.get("fork")]
        non_forks.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)
        top = non_forks[:limit]

        signals = []
        for repo in top:
            full_name = repo["full_name"]
            has_readme = self._path_exists(f"{API_BASE_URL}/repos/{full_name}/readme")
            has_ci = self._path_exists(f"{API_BASE_URL}/repos/{full_name}/contents/.github/workflows")
            pushed_at = repo.get("pushed_at")
            signals.append(
                RepoSignals(
                    name=repo["name"],
                    full_name=full_name,
                    stars=repo.get("stargazers_count", 0),
                    forks=repo.get("forks_count", 0),
                    open_issues=repo.get("open_issues_count", 0),
                    days_since_last_push=_days_since(pushed_at) if pushed_at else 10_000,
                    has_readme=has_readme,
                    has_license=repo.get("license") is not None,
                    has_ci=has_ci,
                )
            )
        return signals
