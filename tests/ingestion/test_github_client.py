import io
import tarfile
from types import SimpleNamespace

import httpx
import pytest

from src.ingestion.github_client import (
    NetworkError,
    RateLimitedError,
    RealGitHubClient,
    RepoNotFoundError,
    RepoPrivateError,
    _auth_headers,
    extract_tarball,
)


def _make_tarball(entries: dict[str, bytes], root: str = "owner-repo-abc123") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in entries.items():
            info = tarfile.TarInfo(name=f"{root}/{path}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _response(status_code: int = 200, json_data: dict | None = None, content: bytes = b"", text: str = "") -> SimpleNamespace:
    def raise_for_status():
        if status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    return SimpleNamespace(
        status_code=status_code,
        json=lambda: json_data or {},
        content=content,
        text=text,
        raise_for_status=raise_for_status,
    )


def test_auth_headers_include_token_when_set():
    headers = _auth_headers("secret-token")
    assert headers["Authorization"] == "Bearer secret-token"


def test_auth_headers_omit_authorization_when_no_token():
    headers = _auth_headers(None)
    assert "Authorization" not in headers


def test_extract_tarball_strips_root_and_returns_files():
    tarball = _make_tarball({"file1.py": b"print(1)", "sub/file2.py": b"print(2)"})

    files = extract_tarball(tarball)

    assert dict(files) == {"file1.py": b"print(1)", "sub/file2.py": b"print(2)"}


def test_extract_tarball_skips_directory_entries():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        dir_info = tarfile.TarInfo(name="owner-repo-abc123/subdir")
        dir_info.type = tarfile.DIRTYPE
        tar.addfile(dir_info)
        file_content = b"hello"
        file_info = tarfile.TarInfo(name="owner-repo-abc123/subdir/a.py")
        file_info.size = len(file_content)
        tar.addfile(file_info, io.BytesIO(file_content))

    files = extract_tarball(buf.getvalue())

    assert files == [("subdir/a.py", b"hello")]


def test_get_repo_metadata_success(monkeypatch):
    responses = [
        _response(200, {"default_branch": "main", "size": 42, "private": False}),
        _response(200, {"sha": "abc123"}),
    ]
    monkeypatch.setattr("httpx.get", lambda *a, **k: responses.pop(0))

    client = RealGitHubClient(token=None)
    meta = client.get_repo_metadata("psf", "requests")

    assert meta.owner == "psf"
    assert meta.repo == "requests"
    assert meta.default_branch == "main"
    assert meta.commit_sha == "abc123"
    assert meta.size_kb == 42


def test_get_repo_metadata_not_found(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **k: _response(404, text="Not Found"))

    with pytest.raises(RepoNotFoundError):
        RealGitHubClient().get_repo_metadata("nope", "nope")


def test_get_repo_metadata_private_repo_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "httpx.get", lambda *a, **k: _response(200, {"default_branch": "main", "size": 1, "private": True})
    )

    with pytest.raises(RepoPrivateError):
        RealGitHubClient().get_repo_metadata("owner", "private-repo")


def test_get_repo_metadata_rate_limited(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **k: _response(403, text="API rate limit exceeded"))

    with pytest.raises(RateLimitedError):
        RealGitHubClient().get_repo_metadata("owner", "repo")


def test_get_repo_metadata_network_error_is_wrapped(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.get", _raise)

    with pytest.raises(NetworkError):
        RealGitHubClient().get_repo_metadata("owner", "repo")


def test_download_source_files_extracts_the_tarball(monkeypatch):
    tarball = _make_tarball({"main.py": b"print('hi')"})
    monkeypatch.setattr("httpx.get", lambda *a, **k: _response(200, content=tarball))

    files = RealGitHubClient().download_source_files("owner", "repo", "abc123")

    assert files == [("main.py", b"print('hi')")]
