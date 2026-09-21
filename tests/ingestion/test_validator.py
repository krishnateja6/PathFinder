import pytest

from src.ingestion.validator import InvalidGitHubURLError, parse_github_url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/psf/requests",
        "http://github.com/psf/requests",
        "github.com/psf/requests",
        "https://www.github.com/psf/requests",
        "https://github.com/psf/requests.git",
        "https://github.com/psf/requests/",
        "  https://github.com/psf/requests  ",
    ],
)
def test_parse_github_url_accepts_valid_variants(url):
    assert parse_github_url(url) == ("psf", "requests")


def test_parse_github_url_handles_dots_and_underscores_in_repo_name():
    assert parse_github_url("https://github.com/owner/my_repo.js") == ("owner", "my_repo.js")


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/psf/requests",
        "https://github.com/psf",
        "https://github.com/psf/requests/issues/123",
        "https://github.com/psf/requests/tree/main",
        "not a url at all",
        "",
        "ftp://github.com/psf/requests",
    ],
)
def test_parse_github_url_rejects_invalid_input(url):
    with pytest.raises(InvalidGitHubURLError):
        parse_github_url(url)
