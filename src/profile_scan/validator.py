"""Validate a GitHub username (spec section 3E's input).

Deliberately independent of src/ingestion/validator.py, which validates
a repository *URL* — a different shape of input, and the profile scan
feature is meant to stand entirely apart from the repo-analysis pipeline.
"""

from __future__ import annotations

import re

# GitHub's own rule: alphanumeric or hyphens, no leading/trailing hyphen,
# no consecutive hyphens, max 39 characters.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


class InvalidGitHubUsernameError(ValueError):
    pass


def validate_github_username(username: str) -> str:
    candidate = username.strip()
    if not _USERNAME_RE.match(candidate):
        raise InvalidGitHubUsernameError(f"not a valid GitHub username: {username!r}")
    return candidate
