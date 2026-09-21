from src.profile_scan.github_client import RepoSignals
from src.profile_scan.scoring import categorize, score_and_categorize, score_repo


def _signals(**overrides) -> RepoSignals:
    defaults = {
        "name": "repo",
        "full_name": "owner/repo",
        "stars": 0,
        "forks": 0,
        "open_issues": 0,
        "days_since_last_push": 1000,
        "has_readme": False,
        "has_license": False,
        "has_ci": False,
    }
    defaults.update(overrides)
    return RepoSignals(**defaults)


def test_a_polished_popular_active_repo_scores_high_and_is_a_product():
    signals = _signals(
        stars=600, forks=50, open_issues=3, days_since_last_push=5, has_readme=True, has_license=True, has_ci=True
    )

    score = score_repo(signals)

    assert score == 100  # capped
    assert categorize(signals, score) == "Products"


def test_a_bare_untouched_repo_scores_zero_and_is_an_experiment():
    signals = _signals()

    score = score_repo(signals)

    assert score == 0
    assert categorize(signals, score) == "Experiments"


def test_a_decent_but_incomplete_repo_lands_in_projects():
    signals = _signals(stars=10, forks=2, days_since_last_push=60, has_readme=True, has_license=False, has_ci=False)

    score = score_repo(signals)

    assert 35 <= score < 70
    assert categorize(signals, score) == "Projects"


def test_high_score_without_readme_or_license_is_not_a_product():
    """Products requires completeness signals too, not just a high score
    from stars/activity alone."""
    signals = _signals(stars=600, forks=50, open_issues=3, days_since_last_push=5, has_readme=False, has_license=False)

    score = score_repo(signals)

    assert score >= 70
    assert categorize(signals, score) == "Projects"


def test_score_never_exceeds_max_even_with_everything_maxed():
    signals = _signals(
        stars=10_000, forks=10_000, open_issues=100, days_since_last_push=0, has_readme=True, has_license=True, has_ci=True
    )

    assert score_repo(signals) == 100


def test_score_and_categorize_sorts_by_score_descending():
    low = _signals(name="low", stars=1)
    high = _signals(name="high", stars=600, forks=50, days_since_last_push=5, has_readme=True, has_license=True, has_ci=True)

    results = score_and_categorize([low, high])

    assert [r.name for r in results] == ["high", "low"]


def test_factors_are_human_readable_and_traceable():
    signals = _signals(stars=42, days_since_last_push=10, has_readme=True)

    [result] = score_and_categorize([signals])

    assert result.factors["Stars"] == "42"
    assert result.factors["Last commit"] == "10 days ago"
    assert result.factors["README"] == "yes"
    assert result.factors["License"] == "no"
