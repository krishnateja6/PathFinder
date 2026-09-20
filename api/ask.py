"""Vercel serverless function: POST /api/ask

Runs the same agent loop and citation-verification pass as the CLI's
`ask` command, against this repo (pre-indexed), using the visitor's own
Anthropic API key for every LLM call the request makes. Semantic search
uses chunk embeddings precomputed offline (see webdemo/build_index.py)
plus one live Voyage call per question — using this deployment's own
VOYAGE_API_KEY, never the visitor's — to embed the question itself.

The visitor's API key is used only for this single request's LLM calls.
It is never logged, stored, or written anywhere by this function.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent.loop import ClaudeClient, run_agent
from src.agent.tools import (
    AgentContext,
    find_callees,
    find_callers,
    find_definition,
    read_file,
)
from src.agent.verify import annotate_answer, verify_answer
from src.indexer.embedder import DEFAULT_MODEL, VoyageEmbeddingClient
from src.indexer.graph_builder import build_graph
from webdemo.retrieval import load_chunk_records, rank_chunks

MAX_QUESTION_LENGTH = 500
MAX_TURNS = 5
CHUNK_DATA_PATH = REPO_ROOT / "webdemo" / "data" / "chunk_embeddings.json"

_graph = None
_chunk_records = None
_voyage_client = None


def _graph_singleton():
    global _graph
    if _graph is None:
        _graph = build_graph(REPO_ROOT)
    return _graph


def _chunk_records_singleton() -> list[dict]:
    global _chunk_records
    if _chunk_records is None:
        _chunk_records = load_chunk_records(CHUNK_DATA_PATH) if CHUNK_DATA_PATH.exists() else []
    return _chunk_records


def _voyage_client_singleton() -> VoyageEmbeddingClient:
    global _voyage_client
    if _voyage_client is None:
        _voyage_client = VoyageEmbeddingClient()
    return _voyage_client


def _web_semantic_search(ctx: AgentContext, query: str, limit: int = 5) -> list[dict]:
    vector = ctx.embedding_client.embed([query], model=DEFAULT_MODEL, input_type="query")[0]
    return rank_chunks(vector, _chunk_records_singleton(), limit=limit)


_DISPATCH = {
    "semantic_search": lambda ctx, args: _web_semantic_search(ctx, args["query"], args.get("limit", 5)),
    "read_file": lambda ctx, args: read_file(ctx, args["path"], args.get("start_line"), args.get("end_line")),
    "find_definition": lambda ctx, args: find_definition(ctx, args["symbol"]),
    "find_callers": lambda ctx, args: find_callers(ctx, args["function"]),
    "find_callees": lambda ctx, args: find_callees(ctx, args["function"]),
}


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            self._handle()
        except Exception as exc:  # noqa: BLE001 - always return JSON, never an opaque error page
            self._send_json(500, {"error": f"internal error: {exc}"})

    def do_GET(self) -> None:
        self._send_json(405, {"error": "use POST"})

    def _handle(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(content_length) or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        api_key = (body.get("anthropic_api_key") or "").strip()
        question = (body.get("question") or "").strip()

        if not api_key:
            self._send_json(400, {"error": "anthropic_api_key is required"})
            return
        if not question:
            self._send_json(400, {"error": "question is required"})
            return
        if len(question) > MAX_QUESTION_LENGTH:
            self._send_json(400, {"error": f"question is too long (max {MAX_QUESTION_LENGTH} characters)"})
            return

        ctx = AgentContext(
            repo_root=REPO_ROOT,
            repo_id="pathfinder-demo",
            conn=None,
            embedding_client=_voyage_client_singleton(),
            graph=_graph_singleton(),
        )
        llm = ClaudeClient(api_key=api_key)

        try:
            answer = run_agent(question, ctx, llm, max_turns=MAX_TURNS, dispatch=_DISPATCH)
            verified = verify_answer(answer.text, REPO_ROOT, llm)
        except Exception as exc:  # noqa: BLE001 - surface a clean error to the visitor, not a stack trace
            self._send_json(502, {"error": f"the model or API call failed: {exc}"})
            return

        final_text = annotate_answer(answer.text, verified)
        self._send_json(
            200,
            {
                "answer": final_text,
                "tool_calls": [{"name": tc.name, "input": tc.input} for tc in answer.tool_calls],
            },
        )

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
