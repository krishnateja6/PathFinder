"""Orchestrates parsing, embedding, and storage for the `index` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psycopg

from src.indexer.embedder import EmbeddingClient, embed_chunks
from src.indexer.graph_builder import build_graph
from src.indexer.parser import parse_repo
from src.storage import db, graph_store


@dataclass(frozen=True)
class IndexSummary:
    repo: str
    total_chunks: int
    functions: int
    methods: int
    classes: int
    graph_nodes: int
    graph_edges: int


def index_repo(
    repo_path: Path,
    embedding_client: EmbeddingClient,
    conn: psycopg.Connection,
    repo_id: str | None = None,
    graph_store_dir: Path | None = None,
) -> IndexSummary:
    """Parse, embed, and store every chunk in `repo_path`, and build its graph.

    A full re-index (delete then re-insert) rather than incremental, per
    the spec's v1 scope — the repo is small enough that re-embedding
    everything on each `index` call is acceptable for now.
    """
    repo_path = Path(repo_path).resolve()
    repo_id = repo_id or str(repo_path)

    chunks = parse_repo(repo_path)
    embeddings = embed_chunks(chunks, embedding_client)

    db.init_schema(conn)
    db.delete_repo(conn, repo_id)
    db.upsert_chunks(conn, repo_id, chunks, embeddings)

    graph = build_graph(repo_path)
    graph_store.save_graph(graph, repo_id, store_dir=graph_store_dir)

    return IndexSummary(
        repo=repo_id,
        total_chunks=len(chunks),
        functions=sum(1 for c in chunks if c.kind == "function"),
        methods=sum(1 for c in chunks if c.kind == "method"),
        classes=sum(1 for c in chunks if c.kind == "class"),
        graph_nodes=graph.number_of_nodes(),
        graph_edges=graph.number_of_edges(),
    )
