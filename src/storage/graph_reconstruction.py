"""Rebuild an in-memory structural graph from Postgres.

The serverless-safe sibling of graph_store.load_graph(): instead of
unpickling a file that might not exist on this invocation's disk, pull
this repo's chunks (code_chunks), edges (graph_edges), and full file list
(repo_files, so chunk-less files like an empty __init__.py still become
module nodes, matching build_graph()'s behavior exactly) and reassemble
the graph. Fast at MVP repo-size caps — low thousands of edges at most.
"""

from __future__ import annotations

import networkx as nx
import psycopg

from src.storage import db, repo_files
from src.storage.graph_edges import get_edges


def edges_from_graph(graph: nx.MultiDiGraph) -> list[tuple[str, str, str]]:
    """The (from_id, to_id, edge_type) tuples build_graph()'s output needs
    turned into before graph_edges.replace_edges() can persist them."""
    return [(u, v, data["type"]) for u, v, data in graph.edges(data=True)]


def reconstruct_graph(conn: psycopg.Connection, repo: str) -> nx.MultiDiGraph:
    chunks = db.get_chunks_by_repo(conn, repo)
    edges = get_edges(conn, repo)
    python_files = sorted(p for p in repo_files.list_paths(conn, repo) if p.endswith(".py"))

    graph = nx.MultiDiGraph()
    for path in python_files:
        graph.add_node(path, type="module", path=path)

    for chunk in chunks:
        graph.add_node(
            chunk["id"],
            type="class" if chunk["kind"] == "class" else "function",
            kind=chunk["kind"],
            name=chunk["name"],
            qualified_name=chunk["qualified_name"],
            file=chunk["file"],
            start_line=chunk["start_line"],
            end_line=chunk["end_line"],
            signature=chunk["signature"],
            docstring=chunk["docstring"],
        )

    for from_id, to_id, edge_type in edges:
        graph.add_edge(from_id, to_id, type=edge_type)

    return graph
