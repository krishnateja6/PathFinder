"""Vercel serverless function: the single consolidated entrypoint for
every /api/* route.

Deliberately ONE file with internal routing, not one file per endpoint.
Vercel's Python entrypoint resolution expects a single unambiguous
app/handler for the whole deployment once [tool.vercel].entrypoint is
pinned (see that config's comment in pyproject.toml for the deployment
failure that taught us this) — multiple files each defining their own
top-level `handler` would reintroduce that exact ambiguity, and this
time it wouldn't be fixable the same way (the config only takes one
value). Routing lives entirely in Python (self.path), not in the
filesystem.

Endpoints:
  POST /api/analyze          {github_url}
  GET  /api/analysis         ?owner=&repo=
  GET  /api/architecture     ?owner=&repo=
  GET  /api/files            ?owner=&repo=&path=(optional)
  POST /api/ask              {owner, repo, anthropic_api_key, question}
  GET  /api/impact           ?owner=&repo=&symbol=
  POST /api/profile_scan     {github_username}
  POST /api/profile_feedback {repo_full_name, anthropic_api_key}

The last two are the GitHub Profile Scan feature (spec section 3E) — a
separate, simpler feature that does not depend on or modify the
repo-analysis pipeline above (src/profile_scan/ is its own package).
They share this file purely for the single-entrypoint deployment reason
explained above, not because the features are coupled.

Every visitor-supplied Anthropic API key is used only for that single
request's LLM calls and is never logged or stored. VOYAGE_API_KEY and
GITHUB_TOKEN are server-side secrets, read from the environment, never
accepted from or returned to the frontend.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent.loop import ClaudeClient, run_agent
from src.agent.tools import (
    MAX_READ_LINES,
    AgentContext,
    analyze_impact,
    find_callees,
    find_callers,
    find_definition,
    semantic_search,
)
from src.agent.verify import annotate_answer, verify_answer
from src.analysis.components import derive_components
from src.analysis.impact import compute_impact
from src.indexer.embedder import VoyageEmbeddingClient
from src.indexer.tech_stack import detect_tech_stack
from src.ingestion.github_client import (
    GitHubError,
    NetworkError,
    RateLimitedError,
    RealGitHubClient,
    RepoNotFoundError,
    RepoPrivateError,
)
from src.ingestion.pipeline import analyze_github_repo
from src.ingestion.source_filter import RepoTooLargeError
from src.ingestion.validator import InvalidGitHubURLError, parse_github_url
from src.profile_scan.github_client import (
    DEFAULT_LIMIT as PROFILE_SCAN_LIMIT,
)
from src.profile_scan.github_client import (
    NetworkError as ProfileNetworkError,
)
from src.profile_scan.github_client import (
    RateLimitedError as ProfileRateLimitedError,
)
from src.profile_scan.github_client import (
    RealGitHubProfileClient,
    UserNotFoundError,
)
from src.profile_scan.scoring import score_and_categorize
from src.profile_scan.validator import InvalidGitHubUsernameError, validate_github_username
from src.storage import analyses, db, repo_files
from src.storage.graph_edges import init_schema as init_graph_edges_schema
from src.storage.graph_reconstruction import reconstruct_graph
from src.storage.repo_files import init_schema as init_repo_files_schema

MAX_QUESTION_LENGTH = 500
MAX_TURNS = 5

_voyage_client: VoyageEmbeddingClient | None = None
_github_client: RealGitHubClient | None = None
_profile_github_client: RealGitHubProfileClient | None = None


def _voyage_client_singleton() -> VoyageEmbeddingClient:
    global _voyage_client
    if _voyage_client is None:
        _voyage_client = VoyageEmbeddingClient()
    return _voyage_client


def _github_client_singleton() -> RealGitHubClient:
    global _github_client
    if _github_client is None:
        _github_client = RealGitHubClient()
    return _github_client


def _profile_github_client_singleton() -> RealGitHubProfileClient:
    global _profile_github_client
    if _profile_github_client is None:
        _profile_github_client = RealGitHubProfileClient()
    return _profile_github_client


def _init_all_schemas(conn) -> None:
    db.init_schema(conn)
    analyses.init_schema(conn)
    init_graph_edges_schema(conn)
    init_repo_files_schema(conn)


def _resolve_analysis(conn, owner: str, repo: str) -> analyses.Analysis | None:
    """The latest *ready* analysis for owner/repo, regardless of commit."""
    return analyses.get_latest_ready_analysis(conn, analyses.repo_key(owner, repo))


def _postgres_read_file(conn, repo_id: str, path: str, start_line: int | None, end_line: int | None) -> dict:
    content = repo_files.get_file(conn, repo_id, path)
    if content is None:
        return {"error": f"no such file: {path}"}
    lines = content.splitlines()
    start = max(1, start_line or 1)
    end = min(len(lines), end_line or len(lines))
    if end - start + 1 > MAX_READ_LINES:
        end = start + MAX_READ_LINES - 1
    return {"path": path, "start_line": start, "end_line": end, "content": "\n".join(lines[start - 1 : end])}


def _postgres_excerpt_reader(conn, repo_id: str, citation) -> str | None:
    """The Postgres-backed sibling of verify.py's disk-based _read_excerpt:
    the cited line range only, not the whole file."""
    content = repo_files.get_file(conn, repo_id, citation.file)
    if content is None:
        return None
    lines = content.splitlines()
    if citation.start_line < 1 or citation.start_line > len(lines):
        return None
    end = min(len(lines), citation.end_line)
    return "\n".join(lines[citation.start_line - 1 : end])


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        route = _ROUTES.get((method, path))
        if route is None:
            self._send_json(404, {"error": f"no route for {method} {path}"})
            return

        try:
            body = self._read_json_body() if method == "POST" else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        try:
            route(self, query, body)
        except psycopg.OperationalError as exc:
            self._send_json(503, {"error": f"could not connect to the database: {exc}", "code": "db_unavailable"})
        except Exception as exc:  # noqa: BLE001 - always return JSON, never an opaque error page
            self._send_json(500, {"error": f"internal error: {exc}"})

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(content_length) if content_length else b""
        return json.loads(raw or b"{}")

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- POST /api/analyze ----

    def handle_analyze(self, query: dict, body: dict) -> None:
        github_url = (body.get("github_url") or "").strip()
        if not github_url:
            self._send_json(400, {"error": "github_url is required"})
            return

        # Validate before touching the database at all: a malformed URL
        # should never depend on — or be masked by — a DB connection issue.
        try:
            parse_github_url(github_url)
        except InvalidGitHubURLError as exc:
            self._send_json(400, {"error": str(exc), "code": "invalid_url"})
            return

        conn = db.connect()
        try:
            _init_all_schemas(conn)
            summary = analyze_github_repo(
                github_url, conn, _voyage_client_singleton(), _github_client_singleton()
            )
        except InvalidGitHubURLError as exc:
            self._send_json(400, {"error": str(exc), "code": "invalid_url"})
            return
        except RepoNotFoundError as exc:
            self._send_json(404, {"error": str(exc), "code": "not_found"})
            return
        except RepoPrivateError as exc:
            self._send_json(403, {"error": str(exc), "code": "private_repo"})
            return
        except RateLimitedError as exc:
            self._send_json(429, {"error": str(exc), "code": "rate_limited"})
            return
        except RepoTooLargeError as exc:
            self._send_json(413, {"error": str(exc), "code": "too_large"})
            return
        except NetworkError as exc:
            self._send_json(502, {"error": str(exc), "code": "network_error"})
            return
        except GitHubError as exc:
            self._send_json(502, {"error": str(exc), "code": "github_error"})
            return
        finally:
            conn.close()

        owner, repo = summary.repo_key.split("/", 1)
        self._send_json(
            200,
            {
                "owner": owner,
                "repo": repo,
                "commit_sha": summary.commit_sha,
                "cached": summary.cached,
                "file_count": summary.file_count,
                "chunk_count": summary.chunk_count,
                "languages": summary.tech_stack.languages,
                "frameworks_hint": summary.tech_stack.frameworks_hint,
            },
        )

    # ---- GET /api/analysis ----

    def handle_analysis(self, query: dict, body: dict) -> None:
        owner, repo = query.get("owner"), query.get("repo")
        if not owner or not repo:
            self._send_json(400, {"error": "owner and repo are required"})
            return

        conn = db.connect()
        try:
            _init_all_schemas(conn)
            record = _resolve_analysis(conn, owner, repo)
            if record is None:
                self._send_json(404, {"error": f"{owner}/{repo} has not been analyzed yet", "code": "not_analyzed"})
                return
            repo_id = analyses.repo_id(owner, repo, record.commit_sha)
            tech_stack = detect_tech_stack(repo_files.list_paths(conn, repo_id))
        finally:
            conn.close()

        self._send_json(
            200,
            {
                "owner": owner,
                "repo": repo,
                "commit_sha": record.commit_sha,
                "default_branch": record.default_branch,
                "file_count": record.file_count,
                "chunk_count": record.chunk_count,
                "languages": tech_stack.languages,
                "frameworks_hint": tech_stack.frameworks_hint,
            },
        )

    # ---- GET /api/architecture ----

    def handle_architecture(self, query: dict, body: dict) -> None:
        owner, repo = query.get("owner"), query.get("repo")
        if not owner or not repo:
            self._send_json(400, {"error": "owner and repo are required"})
            return

        conn = db.connect()
        try:
            _init_all_schemas(conn)
            record = _resolve_analysis(conn, owner, repo)
            if record is None:
                self._send_json(404, {"error": f"{owner}/{repo} has not been analyzed yet", "code": "not_analyzed"})
                return
            repo_id = analyses.repo_id(owner, repo, record.commit_sha)
            graph = reconstruct_graph(conn, repo_id)
        finally:
            conn.close()

        component_graph = derive_components(graph)
        self._send_json(
            200,
            {
                "components": [{"id": c.id, "files": c.files} for c in component_graph.components],
                "edges": [
                    {"source": e.source, "target": e.target, "import_count": e.import_count}
                    for e in component_graph.edges
                ],
                "within_recommended_range": component_graph.is_within_recommended_range(),
            },
        )

    # ---- GET /api/files ----

    def handle_files(self, query: dict, body: dict) -> None:
        owner, repo, path = query.get("owner"), query.get("repo"), query.get("path")
        if not owner or not repo:
            self._send_json(400, {"error": "owner and repo are required"})
            return

        conn = db.connect()
        try:
            _init_all_schemas(conn)
            record = _resolve_analysis(conn, owner, repo)
            if record is None:
                self._send_json(404, {"error": f"{owner}/{repo} has not been analyzed yet", "code": "not_analyzed"})
                return
            repo_id = analyses.repo_id(owner, repo, record.commit_sha)

            if path:
                content = repo_files.get_file(conn, repo_id, path)
                if content is None:
                    self._send_json(404, {"error": f"no such file: {path}"})
                    return
                self._send_json(200, {"path": path, "content": content})
                return

            paths = repo_files.list_paths(conn, repo_id)
        finally:
            conn.close()

        self._send_json(200, {"paths": paths})

    # ---- GET /api/impact ----

    def handle_impact(self, query: dict, body: dict) -> None:
        owner, repo, symbol = query.get("owner"), query.get("repo"), query.get("symbol")
        if not owner or not repo or not symbol:
            self._send_json(400, {"error": "owner, repo, and symbol are required"})
            return

        conn = db.connect()
        try:
            _init_all_schemas(conn)
            record = _resolve_analysis(conn, owner, repo)
            if record is None:
                self._send_json(404, {"error": f"{owner}/{repo} has not been analyzed yet", "code": "not_analyzed"})
                return
            repo_id = analyses.repo_id(owner, repo, record.commit_sha)
            graph = reconstruct_graph(conn, repo_id)
        finally:
            conn.close()

        result = compute_impact(graph, symbol)
        if not result.targets:
            self._send_json(404, {"error": f"no function, class, or file named '{symbol}' found"})
            return

        def _describe(items):
            return [
                {
                    "qualified_name": s.qualified_name,
                    "kind": s.kind,
                    "file": s.file,
                    "start_line": s.start_line,
                    "via": s.via,
                }
                for s in items
            ]

        self._send_json(200, {"targets": _describe(result.targets), "affected": _describe(result.affected)})

    # ---- POST /api/ask ----

    def handle_ask(self, query: dict, body: dict) -> None:
        owner = (body.get("owner") or "").strip()
        repo = (body.get("repo") or "").strip()
        api_key = (body.get("anthropic_api_key") or "").strip()
        question = (body.get("question") or "").strip()

        if not owner or not repo:
            self._send_json(400, {"error": "owner and repo are required"})
            return
        if not api_key:
            self._send_json(400, {"error": "anthropic_api_key is required"})
            return
        if not question:
            self._send_json(400, {"error": "question is required"})
            return
        if len(question) > MAX_QUESTION_LENGTH:
            self._send_json(400, {"error": f"question is too long (max {MAX_QUESTION_LENGTH} characters)"})
            return

        conn = db.connect()
        try:
            _init_all_schemas(conn)
            record = _resolve_analysis(conn, owner, repo)
            if record is None:
                self._send_json(404, {"error": f"{owner}/{repo} has not been analyzed yet", "code": "not_analyzed"})
                return
            repo_id = analyses.repo_id(owner, repo, record.commit_sha)
            graph = reconstruct_graph(conn, repo_id)

            ctx = AgentContext(
                repo_root=REPO_ROOT,  # unused: read_file is overridden below to read from Postgres
                repo_id=repo_id,
                conn=conn,
                embedding_client=_voyage_client_singleton(),
                graph=graph,
            )
            llm = ClaudeClient(api_key=api_key)
            dispatch = {
                "semantic_search": lambda ctx, args: semantic_search(ctx, args["query"], limit=args.get("limit", 5)),
                "read_file": lambda ctx, args: _postgres_read_file(
                    conn, repo_id, args["path"], args.get("start_line"), args.get("end_line")
                ),
                "find_definition": lambda ctx, args: find_definition(ctx, args["symbol"]),
                "find_callers": lambda ctx, args: find_callers(ctx, args["function"]),
                "find_callees": lambda ctx, args: find_callees(ctx, args["function"]),
                "analyze_impact": lambda ctx, args: analyze_impact(ctx, args["symbol"]),
            }

            try:
                answer = run_agent(question, ctx, llm, max_turns=MAX_TURNS, dispatch=dispatch)
                verified = verify_answer(
                    answer.text,
                    REPO_ROOT,
                    llm,
                    excerpt_reader=lambda citation: _postgres_excerpt_reader(conn, repo_id, citation),
                )
            except Exception as exc:  # noqa: BLE001 - surface a clean error, not a stack trace
                self._send_json(502, {"error": f"the model or API call failed: {exc}"})
                return
        finally:
            conn.close()

        self._send_json(
            200,
            {
                "answer": annotate_answer(answer.text, verified),
                "tool_calls": [{"name": tc.name, "input": tc.input} for tc in answer.tool_calls],
            },
        )

    # ---- POST /api/profile_scan ----
    # GitHub Profile Scan (spec section 3E) — independent of the
    # repo-analysis pipeline above: no caching, no Postgres, no
    # structural analysis. Stateless on every call, by design.

    def handle_profile_scan(self, query: dict, body: dict) -> None:
        username_input = (body.get("github_username") or "").strip()
        if not username_input:
            self._send_json(400, {"error": "github_username is required"})
            return

        try:
            username = validate_github_username(username_input)
        except InvalidGitHubUsernameError as exc:
            self._send_json(400, {"error": str(exc), "code": "invalid_username"})
            return

        try:
            signals = _profile_github_client_singleton().list_repo_signals(username, limit=PROFILE_SCAN_LIMIT)
        except UserNotFoundError as exc:
            self._send_json(404, {"error": str(exc), "code": "not_found"})
            return
        except ProfileRateLimitedError as exc:
            self._send_json(429, {"error": str(exc), "code": "rate_limited"})
            return
        except ProfileNetworkError as exc:
            self._send_json(502, {"error": str(exc), "code": "network_error"})
            return

        scored = score_and_categorize(signals)
        self._send_json(
            200,
            {
                "username": username,
                "repos": [
                    {"name": r.name, "full_name": r.full_name, "score": r.score, "bucket": r.bucket, "factors": r.factors}
                    for r in scored
                ],
            },
        )

    # ---- POST /api/profile_feedback ----

    def handle_profile_feedback(self, query: dict, body: dict) -> None:
        full_name = (body.get("repo_full_name") or "").strip()
        api_key = (body.get("anthropic_api_key") or "").strip()

        if not full_name:
            self._send_json(400, {"error": "repo_full_name is required"})
            return
        if not api_key:
            self._send_json(400, {"error": "anthropic_api_key is required"})
            return

        try:
            readme = _profile_github_client_singleton().get_readme_content(full_name)
        except ProfileRateLimitedError as exc:
            self._send_json(429, {"error": str(exc), "code": "rate_limited"})
            return
        except ProfileNetworkError as exc:
            self._send_json(502, {"error": str(exc), "code": "network_error"})
            return

        if readme is None:
            self._send_json(404, {"error": f"{full_name} has no README to review"})
            return

        try:
            llm = ClaudeClient(api_key=api_key)
            response = llm.create(
                system=_PROFILE_FEEDBACK_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"README for {full_name}:\n\n{readme}"}],
                tools=[],
            )
        except Exception as exc:  # noqa: BLE001 - surface a clean error, not a stack trace
            self._send_json(502, {"error": f"the model call failed: {exc}"})
            return

        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        self._send_json(
            200,
            {
                "repo_full_name": full_name,
                "feedback": text,
                "disclaimer": "AI interpretation of the README only, not a verified fact about the code.",
            },
        )


_PROFILE_FEEDBACK_SYSTEM_PROMPT = """You review a single GitHub repository's README to give \
honest, direct feedback on it as a portfolio piece. You will be shown the README's raw content. \
Respond with three short sections, each 1-3 sentences: STRENGTHS: ... WEAKNESSES: ... \
RESUME-WORTHY: yes/no/maybe, with one sentence why. Base your answer only on what the README \
actually says — this is your interpretation of the README, not a verified fact about the \
underlying code, and you should not claim otherwise."""


_ROUTES = {
    ("POST", "/api/analyze"): handler.handle_analyze,
    ("GET", "/api/analysis"): handler.handle_analysis,
    ("GET", "/api/architecture"): handler.handle_architecture,
    ("GET", "/api/files"): handler.handle_files,
    ("GET", "/api/impact"): handler.handle_impact,
    ("POST", "/api/ask"): handler.handle_ask,
    ("POST", "/api/profile_scan"): handler.handle_profile_scan,
    ("POST", "/api/profile_feedback"): handler.handle_profile_feedback,
}
