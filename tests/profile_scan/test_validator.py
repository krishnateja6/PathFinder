import pytest

from src.profile_scan.validator import InvalidGitHubUsernameError, validate_github_username


@pytest.mark.parametrize("username", ["octocat", "torvalds", "a", "foo-bar", "foo123", "  spaced  "])
def test_accepts_valid_usernames(username):
    assert validate_github_username(username) == username.strip()


@pytest.mark.parametrize(
    "username",
    [
        "-foo",
        "foo-",
        "foo--bar",
        "",
        "a" * 40,
        "foo bar",
        "foo/bar",
        "foo@bar",
    ],
)
def test_rejects_invalid_usernames(username):
    with pytest.raises(InvalidGitHubUsernameError):
        validate_github_username(username)
