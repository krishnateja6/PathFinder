"""Validate and parse a public GitHub repository URL into (owner, repo).

Deliberately narrow: HTTPS web URLs only (what a visitor would paste from
their browser's address bar), no SSH remotes, no sub-paths like /issues or
/tree/branch — those aren't "a repository," they're a page within one.
"""

from __future__ import annotations

import re

_GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/"
    r"(?P<repo>[A-Za-z0-9._-]+?)"
    r"(?:\.git)?/?$"
)


class InvalidGitHubURLError(ValueError):
    pass


def parse_github_url(url: str) -> tuple[str, str]:
    """Return (owner, repo) from a public GitHub repository URL.

    Accepts with/without a URL scheme, with/without a trailing `.git`,
    with/without a trailing slash. Raises InvalidGitHubURLError for
    anything else: a non-GitHub host, a URL with extra path segments
    (`/issues`, `/tree/main`, ...), or a string that isn't a URL at all.
    """
    candidate = url.strip()
    match = _GITHUB_URL_RE.match(candidate)
    if not match:
        raise InvalidGitHubURLError(f"not a valid GitHub repository URL: {url!r}")
    return match.group("owner"), match.group("repo")
