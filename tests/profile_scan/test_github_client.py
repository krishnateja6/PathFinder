from types import SimpleNamespace

import httpx
import pytest

from src.profile_scan.github_client import (
    RateLimitedError,
    RealGitHubProfileClient,
    UserNotFoundError,
)


def _response(status_code: int = 200, json_data=None, text: str = "") -> SimpleNamespace:
    def raise_for_status():
        if status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    return SimpleNamespace(status_code=status_code, json=lambda: json_data, text=text, raise_for_status=raise_for_status)


def _repo(name, full_name, stars=0, forks=0, issues=0, fork=False, license_present=True, pushed_at="2020-01-01T00:00:00Z"):
    return {
        "name": name,
        "full_name": full_name,
        "stargazers_count": stars,
        "forks_count": forks,
        "open_issues_count": issues,
        "fork": fork,
        "license": {"key": "mit"} if license_present else None,
        "pushed_at": pushed_at,
    }


def test_list_repo_signals_excludes_forks_and_sorts_by_stars(monkeypatch):
    repos = [
        _repo("popular", "octo/popular", stars=100),
        _repo("forked", "octo/forked", stars=999, fork=True),
        _repo("small", "octo/small", stars=5),
    ]
    responses = [
        _response(200, repos),  # repo list
        _response(200, {}),  # popular: readme exists
        _response(404, None),  # popular: no ci
        _response(404, None),  # small: no readme
        _response(404, None),  # small: no ci
    ]
    monkeypatch.setattr("httpx.get", lambda *a, **k: responses.pop(0))

    signals = RealGitHubProfileClient(token=None).list_repo_signals("octo", limit=10)

    assert [s.name for s in signals] == ["popular", "small"]
    assert signals[0].has_readme is True
    assert signals[0].has_ci is False
    assert signals[1].has_readme is False


def test_list_repo_signals_respects_limit(monkeypatch):
    repos = [_repo(f"r{i}", f"octo/r{i}", stars=i) for i in range(5)]
    call_log = [_response(200, repos)]
    # 2 repos kept (limit=2) -> 2 * 2 extra calls
    call_log += [_response(404, None)] * 4
    monkeypatch.setattr("httpx.get", lambda *a, **k: call_log.pop(0))

    signals = RealGitHubProfileClient(token=None).list_repo_signals("octo", limit=2)

    assert len(signals) == 2
    assert signals[0].name == "r4"  # highest stars
    assert signals[1].name == "r3"


def test_list_repo_signals_raises_user_not_found(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **k: _response(404, None))

    with pytest.raises(UserNotFoundError):
        RealGitHubProfileClient(token=None).list_repo_signals("nonexistent")


def test_list_repo_signals_raises_rate_limited(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **k: _response(403, text="API rate limit exceeded"))

    with pytest.raises(RateLimitedError):
        RealGitHubProfileClient(token=None).list_repo_signals("octo")


def test_get_readme_content_returns_raw_text(monkeypatch):
    response = SimpleNamespace(status_code=200, text="# My Project\nDescription.", raise_for_status=lambda: None)
    monkeypatch.setattr("httpx.get", lambda *a, **k: response)

    content = RealGitHubProfileClient(token=None).get_readme_content("octo/repo")

    assert content == "# My Project\nDescription."


def test_get_readme_content_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **k: _response(404, None))

    assert RealGitHubProfileClient(token=None).get_readme_content("octo/repo") is None


def test_has_license_reflects_the_repo_list_response_directly(monkeypatch):
    repos = [_repo("a", "octo/a", license_present=False)]
    responses = [_response(200, repos), _response(404, None), _response(404, None)]
    monkeypatch.setattr("httpx.get", lambda *a, **k: responses.pop(0))

    signals = RealGitHubProfileClient(token=None).list_repo_signals("octo")

    assert signals[0].has_license is False
