"""Thin GitHub REST API client: repo metadata + source download.

Behind a small Protocol so ingestion logic can be tested without real
network access — the same pattern as EmbeddingClient (src/indexer/embedder.py)
and LLMClient (src/agent/loop.py) elsewhere in this codebase.
"""

from __future__ import annotations

import io
import os
import tarfile
from dataclasses import dataclass
from typing import Protocol

API_BASE_URL = "https://api.github.com"
_TIMEOUT_METADATA_SECONDS = 10.0
_TIMEOUT_DOWNLOAD_SECONDS = 30.0


class GitHubError(Exception):
    """Base class for all GitHub-ingestion-related failures."""


class RepoNotFoundError(GitHubError):
    pass


class RepoPrivateError(GitHubError):
    pass


class RateLimitedError(GitHubError):
    pass


class NetworkError(GitHubError):
    pass


@dataclass(frozen=True)
class RepoMetadata:
    owner: str
    repo: str
    default_branch: str
    commit_sha: str
    size_kb: int


class GitHubClient(Protocol):
    def get_repo_metadata(self, owner: str, repo: str) -> RepoMetadata: ...
    def download_source_files(self, owner: str, repo: str, commit_sha: str) -> list[tuple[str, bytes]]: ...


def _is_rate_limited(status_code: int, body_text: str) -> bool:
    return status_code == 403 and "rate limit" in body_text.lower()


def _auth_headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def extract_tarball(content: bytes) -> list[tuple[str, bytes]]:
    """Unpack a GitHub tarball's files, stripping its `<owner>-<repo>-<sha>/` root."""
    files: list[tuple[str, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            if len(parts) != 2:
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            files.append((parts[1], extracted.read()))
    return files


class RealGitHubClient:
    """httpx-backed implementation.

    Uses a server-side GITHUB_TOKEN if set, for the higher (5,000 req/hr)
    rate limit; falls back to unauthenticated (60 req/hr) otherwise. The
    token is never sent to or accepted from the frontend.
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN")

    def get_repo_metadata(self, owner: str, repo: str) -> RepoMetadata:
        import httpx

        headers = _auth_headers(self._token)
        try:
            repo_resp = httpx.get(f"{API_BASE_URL}/repos/{owner}/{repo}", headers=headers, timeout=_TIMEOUT_METADATA_SECONDS)
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc

        if repo_resp.status_code == 404:
            raise RepoNotFoundError(f"{owner}/{repo} not found")
        if _is_rate_limited(repo_resp.status_code, repo_resp.text):
            raise RateLimitedError("GitHub API rate limit exceeded")
        repo_resp.raise_for_status()
        data = repo_resp.json()

        if data.get("private"):
            raise RepoPrivateError(f"{owner}/{repo} is private")

        default_branch = data["default_branch"]

        try:
            commit_resp = httpx.get(
                f"{API_BASE_URL}/repos/{owner}/{repo}/commits/{default_branch}",
                headers=headers,
                timeout=_TIMEOUT_METADATA_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        if _is_rate_limited(commit_resp.status_code, commit_resp.text):
            raise RateLimitedError("GitHub API rate limit exceeded")
        commit_resp.raise_for_status()

        return RepoMetadata(
            owner=owner,
            repo=repo,
            default_branch=default_branch,
            commit_sha=commit_resp.json()["sha"],
            size_kb=data.get("size", 0),
        )

    def download_source_files(self, owner: str, repo: str, commit_sha: str) -> list[tuple[str, bytes]]:
        import httpx

        url = f"{API_BASE_URL}/repos/{owner}/{repo}/tarball/{commit_sha}"
        try:
            response = httpx.get(
                url, headers=_auth_headers(self._token), timeout=_TIMEOUT_DOWNLOAD_SECONDS, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        if _is_rate_limited(response.status_code, response.text):
            raise RateLimitedError("GitHub API rate limit exceeded")
        response.raise_for_status()
        return extract_tarball(response.content)
