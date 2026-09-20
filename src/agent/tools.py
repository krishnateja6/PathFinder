"""The five tools given to the agentic Q&A loop (spec §3.2).

Each tool is a plain, testable function taking an explicit `AgentContext`
rather than reaching for module-level globals — the agent loop's
dispatch table maps Claude's tool_use names onto these directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import psycopg

from src.indexer.embedder import DEFAULT_MODEL, EmbeddingClient
from src.storage import db

MAX_READ_LINES = 400


@dataclass
class AgentContext:
    repo_root: Path
    repo_id: str
    conn: psycopg.Connection
    embedding_client: EmbeddingClient
    graph: nx.MultiDiGraph


def semantic_search(ctx: AgentContext, query: str, limit: int = 5) -> list[dict]:
    """Embedding similarity search over the indexed code."""
    vector = ctx.embedding_client.embed([query], model=DEFAULT_MODEL, input_type="query")[0]
    results = db.semantic_search(ctx.conn, ctx.repo_id, vector, limit=limit)
    return [
        {
            "qualified_name": r["qualified_name"],
            "kind": r["kind"],
            "file": r["file"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "signature": r["signature"],
            "docstring": r["docstring"],
        }
        for r in results
    ]


def read_file(ctx: AgentContext, path: str, start_line: int | None = None, end_line: int | None = None) -> dict:
    """Read exact source lines from a file in the indexed repo."""
    repo_root = ctx.repo_root.resolve()
    full_path = (repo_root / path).resolve()
    if full_path != repo_root and repo_root not in full_path.parents:
        return {"error": f"{path} is outside the indexed repo"}
    if not full_path.is_file():
        return {"error": f"no such file: {path}"}

    lines = full_path.read_text().splitlines()
    start = max(1, start_line or 1)
    end = min(len(lines), end_line or len(lines))
    if end - start + 1 > MAX_READ_LINES:
        end = start + MAX_READ_LINES - 1
    content = "\n".join(lines[start - 1 : end])
    return {"path": path, "start_line": start, "end_line": end, "content": content}


def _find_nodes(graph: nx.MultiDiGraph, symbol: str) -> list[tuple[str, dict]]:
    return [
        (node, data)
        for node, data in graph.nodes(data=True)
        if data.get("type") in ("function", "class") and symbol in (data.get("qualified_name"), data.get("name"))
    ]


def _describe(data: dict) -> dict:
    return {
        "qualified_name": data["qualified_name"],
        "kind": data["kind"],
        "file": data["file"],
        "start_line": data["start_line"],
        "end_line": data["end_line"],
        "signature": data["signature"],
        "docstring": data["docstring"],
    }


def find_definition(ctx: AgentContext, symbol: str) -> list[dict]:
    """Graph lookup: where a function, method, or class is defined."""
    return [_describe(data) for _, data in _find_nodes(ctx.graph, symbol)]


def _related(ctx: AgentContext, symbol: str, *, direction: str) -> list[dict]:
    edges_fn = ctx.graph.in_edges if direction == "callers" else ctx.graph.out_edges
    results = []
    for node, _ in _find_nodes(ctx.graph, symbol):
        for u, v, data in edges_fn(node, data=True):
            if data.get("type") != "CALLS":
                continue
            other = u if direction == "callers" else v
            other_data = ctx.graph.nodes[other]
            results.append(
                {
                    "qualified_name": other_data["qualified_name"],
                    "file": other_data["file"],
                    "start_line": other_data["start_line"],
                }
            )
    return results


def find_callers(ctx: AgentContext, function: str) -> list[dict]:
    """Graph lookup: who calls this function/method."""
    return _related(ctx, function, direction="callers")


def find_callees(ctx: AgentContext, function: str) -> list[dict]:
    """Graph lookup: what this function/method calls."""
    return _related(ctx, function, direction="callees")
