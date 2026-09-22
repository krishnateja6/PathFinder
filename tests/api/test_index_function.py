"""Integration tests for the consolidated /api/* Vercel function.

Runs the actual handler class against a real local HTTPServer (bypassing
Vercel entirely) with a real Postgres connection, so this exercises the
genuine wire contract and multi-table persistence, not just mocked
Python objects. Loaded from its file path since api/ isn't a Python
package (Vercel treats every .py file directly under api/ as its own
route, so it deliberately has no __init__.py).
"""

import importlib.util
import json
import threading
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from src.ingestion.github_client import RepoMetadata

INDEX_PATH = Path(__file__).parents[2] / "api" / "index.py"

METADATA = RepoMetadata(owner="acme", repo="widget", default_branch="main", commit_sha="deadbeef1234567890", size_kb=5)
FILES = [
    ("main.py", b"from .utils import add\n\ndef run():\n    return add(1, 2)\n"),
    ("utils.py", b"def add(a, b):\n    return a + b\n"),
]


def _load_index_module():
    spec = importlib.util.spec_from_file_location("api_index_under_test", INDEX_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeGitHubClient:
    def __init__(self, metadata=METADATA, files=None):
        self.metadata = metadata
        self.files = files if files is not None else FILES

    def get_repo_metadata(self, owner, repo):
        return self.metadata

    def download_source_files(self, owner, repo, commit_sha):
        return self.files


class FakeVoyageClient:
    def embed(self, texts, model, input_type):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeLLM:
    """Returns `first_response` on the first call (the answer), then
    "SUPPORTED" for every subsequent call (citation verification)."""

    def __init__(self, first_response: str):
        self.first_response = first_response
        self.call_count = 0

    def create(self, *, system, messages, tools):
        self.call_count += 1
        text = self.first_response if self.call_count == 1 else "SUPPORTED"
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


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
def server(pg_conn, monkeypatch):
    module = _load_index_module()
    monkeypatch.setattr(module, "_github_client_singleton", lambda: FakeGitHubClient())
    monkeypatch.setattr(module, "_voyage_client_singleton", lambda: FakeVoyageClient())

    httpd = HTTPServer(("127.0.0.1", 0), module.handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, module
    httpd.shutdown()
    thread.join()


def test_full_flow_analyze_then_every_query_endpoint(server, monkeypatch):
    httpd, module = server
    monkeypatch.setattr(
        module, "ClaudeClient", lambda api_key: FakeLLM("run() calls add(), defined at utils.py:1-2.")
    )

    status, analyzed = _request(
        httpd, "POST", "/api/analyze", {"github_url": "https://github.com/test-acme/widget"}
    )
    assert status == 200
    assert analyzed == {
        "owner": "test-acme",
        "repo": "widget",
        "commit_sha": "deadbeef1234567890",
        "cached": False,
        "file_count": 2,
        "chunk_count": 2,
        "languages": {"Python": 2},
        "frameworks_hint": [],
    }

    status, analyzed_again = _request(
        httpd, "POST", "/api/analyze", {"github_url": "https://github.com/test-acme/widget"}
    )
    assert status == 200
    assert analyzed_again["cached"] is True

    status, analysis = _request(httpd, "GET", "/api/analysis?owner=test-acme&repo=widget")
    assert status == 200
    assert analysis["commit_sha"] == "deadbeef1234567890"
    assert analysis["chunk_count"] == 2
    # regression: /api/analysis must carry tech-stack info too, not just
    # /api/analyze's initial response, or the Overview tab is empty on reload
    assert analysis["languages"] == {"Python": 2}

    status, architecture = _request(httpd, "GET", "/api/architecture?owner=test-acme&repo=widget")
    assert status == 200
    assert len(architecture["components"]) == 1
    assert architecture["components"][0]["files"] == ["main.py", "utils.py"]

    status, files = _request(httpd, "GET", "/api/files?owner=test-acme&repo=widget")
    assert status == 200
    assert set(files["paths"]) == {"main.py", "utils.py"}

    status, one_file = _request(httpd, "GET", "/api/files?owner=test-acme&repo=widget&path=utils.py")
    assert status == 200
    assert one_file["content"] == "def add(a, b):\n    return a + b\n"

    status, impact = _request(httpd, "GET", "/api/impact?owner=test-acme&repo=widget&symbol=add")
    assert status == 200
    assert {a["qualified_name"] for a in impact["affected"]} == {"run"}

    status, ask_result = _request(
        httpd,
        "POST",
        "/api/ask",
        {"owner": "test-acme", "repo": "widget", "anthropic_api_key": "sk-ant-test", "question": "what does run do?"},
    )
    assert status == 200
    assert ask_result["answer"] == "run() calls add(), defined at utils.py:1-2."
    assert "[UNVERIFIED CITATION]" not in ask_result["answer"]


def test_ask_can_use_the_analyze_impact_tool(server, monkeypatch):
    """End-to-end: the chat agent can call analyze_impact and get a real
    graph traversal back, not just find_callers' single-hop view."""
    httpd, module = server
    _request(httpd, "POST", "/api/analyze", {"github_url": "https://github.com/test-acme/widget"})

    class FakeToolUseLLM:
        def __init__(self):
            self.call_count = 0

        def create(self, *, system, messages, tools):
            self.call_count += 1
            if self.call_count == 1:
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use", name="analyze_impact", input={"symbol": "add"}, id="call_1"
                        )
                    ]
                )
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="Changing add() would affect run().")]
            )

    monkeypatch.setattr(module, "ClaudeClient", lambda api_key: FakeToolUseLLM())

    status, result = _request(
        httpd,
        "POST",
        "/api/ask",
        {
            "owner": "test-acme",
            "repo": "widget",
            "anthropic_api_key": "sk-ant-test",
            "question": "what would break if I changed add()?",
        },
    )

    assert status == 200
    assert result["answer"] == "Changing add() would affect run()."
    assert result["tool_calls"] == [{"name": "analyze_impact", "input": {"symbol": "add"}}]


def test_analyze_rejects_missing_github_url(server):
    httpd, _module = server
    status, result = _request(httpd, "POST", "/api/analyze", {})
    assert status == 400
    assert "github_url" in result["error"]


def test_analyze_rejects_an_invalid_github_url(server):
    httpd, _module = server
    status, result = _request(httpd, "POST", "/api/analyze", {"github_url": "not a url"})
    assert status == 400
    assert result["code"] == "invalid_url"


def test_analyze_validates_the_url_before_touching_the_database(server, monkeypatch):
    """Regression: an invalid URL used to reach db.connect() first, so a
    broken DATABASE_URL masked the real "invalid_url" error behind a raw
    internal-error message about DNS/connection failure instead."""
    httpd, module = server

    def _explode(*args, **kwargs):
        raise AssertionError("db.connect() should not be called for an invalid URL")

    monkeypatch.setattr(module.db, "connect", _explode)

    status, result = _request(httpd, "POST", "/api/analyze", {"github_url": "https://github.com/just-a-user"})

    assert status == 400
    assert result["code"] == "invalid_url"


def test_analyze_reports_a_clean_error_when_the_database_is_unreachable(server, monkeypatch):
    """A valid request that can't reach Postgres should get a clear,
    actionable message — not a raw internal error leaking connection
    details (host, credentials) from the exception text."""
    httpd, module = server
    monkeypatch.setattr(
        module.db, "connect", lambda: (_ for _ in ()).throw(psycopg.OperationalError("could not resolve host"))
    )

    status, result = _request(httpd, "POST", "/api/analyze", {"github_url": "https://github.com/test-acme/widget"})

    assert status == 503
    assert result["code"] == "db_unavailable"


def test_query_endpoints_404_when_repo_not_analyzed_yet(server):
    httpd, _module = server

    for method, path in [
        ("GET", "/api/analysis?owner=nope&repo=nope"),
        ("GET", "/api/architecture?owner=nope&repo=nope"),
        ("GET", "/api/files?owner=nope&repo=nope"),
        ("GET", "/api/impact?owner=nope&repo=nope&symbol=x"),
    ]:
        status, result = _request(httpd, method, path)
        assert status == 404, f"{method} {path} expected 404, got {status}"
        assert result["code"] == "not_analyzed"


def test_ask_requires_an_anthropic_api_key(server):
    httpd, _module = server
    _request(httpd, "POST", "/api/analyze", {"github_url": "https://github.com/test-acme/widget"})

    status, result = _request(
        httpd, "POST", "/api/ask", {"owner": "test-acme", "repo": "widget", "question": "hi"}
    )

    assert status == 400
    assert "anthropic_api_key" in result["error"]


def test_unknown_route_is_404(server):
    httpd, _module = server
    status, result = _request(httpd, "GET", "/api/nonexistent")
    assert status == 404
    assert "no route" in result["error"]
