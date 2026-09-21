"""Integration tests for the Profile Scan routes on the consolidated
/api/* function. Deliberately does not use the pg_conn fixture — this
feature touches no database at all, by design (spec section 3E).
"""

import importlib.util
import json
import threading
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.profile_scan.github_client import RepoSignals

INDEX_PATH = Path(__file__).parents[2] / "api" / "index.py"


def _load_index_module():
    spec = importlib.util.spec_from_file_location("api_index_profile_scan_under_test", INDEX_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(httpd: HTTPServer, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    conn = HTTPConnection(*httpd.server_address)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    payload = json.loads(resp.read())
    conn.close()
    return resp.status, payload


@pytest.fixture
def server():
    module = _load_index_module()
    httpd = HTTPServer(("127.0.0.1", 0), module.handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, module
    httpd.shutdown()
    thread.join()


class FakeProfileGitHubClient:
    def __init__(self, signals=None, readme="# A Project\nIt does things."):
        self.signals = signals or [
            RepoSignals(
                name="polished",
                full_name="octo/polished",
                stars=600,
                forks=50,
                open_issues=3,
                days_since_last_push=5,
                has_readme=True,
                has_license=True,
                has_ci=True,
            ),
            RepoSignals(
                name="rough",
                full_name="octo/rough",
                stars=1,
                forks=0,
                open_issues=0,
                days_since_last_push=900,
                has_readme=False,
                has_license=False,
                has_ci=False,
            ),
        ]
        self.readme = readme

    def list_repo_signals(self, username, limit=30):
        return self.signals

    def get_readme_content(self, full_name):
        return self.readme


def test_profile_scan_returns_scored_and_bucketed_repos(server):
    httpd, module = server
    module._profile_github_client = FakeProfileGitHubClient()

    status, result = _request(httpd, "POST", "/api/profile_scan", {"github_username": "octocat"})

    assert status == 200
    assert result["username"] == "octocat"
    names_by_bucket = {r["name"]: r["bucket"] for r in result["repos"]}
    assert names_by_bucket["polished"] == "Products"
    assert names_by_bucket["rough"] == "Experiments"
    assert result["repos"][0]["name"] == "polished"  # sorted by score descending


def test_profile_scan_rejects_missing_username(server):
    httpd, _module = server
    status, result = _request(httpd, "POST", "/api/profile_scan", {})
    assert status == 400
    assert "github_username" in result["error"]


def test_profile_scan_rejects_invalid_username(server):
    httpd, _module = server
    status, result = _request(httpd, "POST", "/api/profile_scan", {"github_username": "-bad-"})
    assert status == 400
    assert result["code"] == "invalid_username"


def test_profile_feedback_returns_labeled_interpretation(server, monkeypatch):
    httpd, module = server
    module._profile_github_client = FakeProfileGitHubClient(readme="# Cool Tool\nDoes cool things.")

    class FakeLLM:
        def create(self, *, system, messages, tools):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text="STRENGTHS: clear purpose. WEAKNESSES: no examples. RESUME-WORTHY: maybe.",
                    )
                ]
            )

    monkeypatch.setattr(module, "ClaudeClient", lambda api_key: FakeLLM())

    status, result = _request(
        httpd,
        "POST",
        "/api/profile_feedback",
        {"repo_full_name": "octo/cool-tool", "anthropic_api_key": "sk-ant-test"},
    )

    assert status == 200
    assert "STRENGTHS" in result["feedback"]
    assert "interpretation" in result["disclaimer"].lower()


def test_profile_feedback_404s_when_repo_has_no_readme(server):
    httpd, module = server
    module._profile_github_client = FakeProfileGitHubClient(readme=None)

    status, result = _request(
        httpd,
        "POST",
        "/api/profile_feedback",
        {"repo_full_name": "octo/no-readme", "anthropic_api_key": "sk-ant-test"},
    )

    assert status == 404
    assert "README" in result["error"]


def test_profile_feedback_requires_an_api_key(server):
    httpd, module = server
    module._profile_github_client = FakeProfileGitHubClient()

    status, result = _request(httpd, "POST", "/api/profile_feedback", {"repo_full_name": "octo/x"})

    assert status == 400
    assert "anthropic_api_key" in result["error"]
