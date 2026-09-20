"""Integration test for the Vercel function's HTTP contract.

Runs the actual handler class against a real (local) HTTPServer —
bypassing Vercel entirely, but exercising the same request/response
code path that runs there, including real JSON parsing and status
codes. Loaded from its file path since api/ isn't a Python package
(Vercel treats every .py file directly under api/ as its own route, so
it deliberately has no __init__.py).
"""

import importlib.util
import json
import threading
from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

ASK_PATH = Path(__file__).parents[2] / "api" / "ask.py"


def _load_ask_module():
    spec = importlib.util.spec_from_file_location("ask_under_test", ASK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def server():
    module = _load_ask_module()
    httpd = HTTPServer(("127.0.0.1", 0), module.handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, module
    httpd.shutdown()
    thread.join()


def _post(httpd: HTTPServer, payload: dict) -> tuple[int, dict]:
    conn = HTTPConnection(*httpd.server_address)
    body = json.dumps(payload).encode("utf-8")
    conn.request("POST", "/api/ask", body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    return resp.status, data


def test_missing_api_key_returns_400(server):
    httpd, _module = server
    status, data = _post(httpd, {"question": "what does this repo do?"})

    assert status == 400
    assert "anthropic_api_key" in data["error"]


def test_missing_question_returns_400(server):
    httpd, _module = server
    status, data = _post(httpd, {"anthropic_api_key": "sk-ant-test"})

    assert status == 400
    assert "question" in data["error"]


def test_question_too_long_returns_400(server):
    httpd, module = server
    status, data = _post(httpd, {"anthropic_api_key": "sk-ant-test", "question": "x" * (module.MAX_QUESTION_LENGTH + 1)})

    assert status == 400
    assert "too long" in data["error"]


def test_get_is_rejected(server):
    httpd, _module = server
    conn = HTTPConnection(*httpd.server_address)
    conn.request("GET", "/api/ask")
    resp = conn.getresponse()
    resp.read()
    conn.close()

    assert resp.status == 405


def test_full_flow_with_mocked_llm_returns_answer_and_trace(server, monkeypatch):
    httpd, module = server

    class FakeLLM:
        def create(self, *, system, messages, tools):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="This repo defines run().")])

    monkeypatch.setattr(module, "ClaudeClient", lambda api_key: FakeLLM())

    status, data = _post(httpd, {"anthropic_api_key": "sk-ant-test", "question": "what does this repo do?"})

    assert status == 200
    assert data["answer"] == "This repo defines run()."
    assert data["tool_calls"] == []
