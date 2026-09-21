"""Deterministic, explainable repo scoring for the GitHub Profile Scan
feature (spec section 3E). No LLM anywhere in this module — every point
is traceable to a concrete signal, and the same signals drive both the
score and the Products/Projects/Experiments bucket.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.profile_scan.github_client import RepoSignals

MAX_SCORE = 100


@dataclass(frozen=True)
class ScoredRepo:
    name: str
    full_name: str
    score: int
    bucket: str  # "Products" | "Projects" | "Experiments"
    factors: dict[str, str]


def _stars_points(stars: int) -> int:
    """Up to 30 points. Tiered rather than linear so a handful of
    heavily-starred repos don't just flatten everything else to zero."""
    if stars >= 500:
        return 30
    if stars >= 100:
        return 25
    if stars >= 20:
        return 18
    if stars >= 5:
        return 10
    if stars >= 1:
        return 4
    return 0


def _activity_points(days_since_last_push: int) -> int:
    """Up to 25 points for recent activity."""
    if days_since_last_push <= 30:
        return 25
    if days_since_last_push <= 90:
        return 18
    if days_since_last_push <= 365:
        return 10
    if days_since_last_push <= 730:
        return 4
    return 0


def _completeness_points(signals: RepoSignals) -> int:
    """Up to 25 points: README, license, CI configured."""
    points = 0
    if signals.has_readme:
        points += 12
    if signals.has_license:
        points += 6
    if signals.has_ci:
        points += 7
    return points


def _engagement_points(signals: RepoSignals) -> int:
    """Up to 20 points: forks and issue activity as a proxy for outside interest."""
    points = 0
    if signals.forks >= 20:
        points += 12
    elif signals.forks >= 5:
        points += 8
    elif signals.forks >= 1:
        points += 4
    if signals.open_issues > 0:
        points += 8
    return points


def score_repo(signals: RepoSignals) -> int:
    return min(
        MAX_SCORE,
        _stars_points(signals.stars)
        + _activity_points(signals.days_since_last_push)
        + _completeness_points(signals)
        + _engagement_points(signals),
    )


def categorize(signals: RepoSignals, score: int) -> str:
    """Products: polished, documented, maintained. Projects: real but
    rougher. Experiments: small, sparse, likely tinkering. Thresholds on
    the same signals used for scoring, not a separate LLM judgment."""
    if score >= 70 and signals.has_readme and signals.has_license:
        return "Products"
    if score >= 35:
        return "Projects"
    return "Experiments"


def _factors(signals: RepoSignals) -> dict[str, str]:
    return {
        "Stars": str(signals.stars),
        "Last commit": f"{signals.days_since_last_push} days ago",
        "README": "yes" if signals.has_readme else "no",
        "License": "yes" if signals.has_license else "no",
        "CI": "yes" if signals.has_ci else "no",
        "Forks": str(signals.forks),
        "Open issues": str(signals.open_issues),
    }


def score_and_categorize(signals_list: list[RepoSignals]) -> list[ScoredRepo]:
    scored = []
    for signals in signals_list:
        score = score_repo(signals)
        scored.append(
            ScoredRepo(
                name=signals.name,
                full_name=signals.full_name,
                score=score,
                bucket=categorize(signals, score),
                factors=_factors(signals),
            )
        )
    return sorted(scored, key=lambda r: r.score, reverse=True)
