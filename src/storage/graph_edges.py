"""Postgres-backed structural graph storage for the web product.

Replaces graph_store.py's pickle-to-local-disk approach, which doesn't
survive serverless deployment (ephemeral disk, not shared across
invocations). The CLI keeps using graph_store.py unchanged for local
runs; this is additive, not a replacement of that path.

Module nodes aren't stored here at all — they're just the distinct
`file` values already in code_chunks, reconstructed on demand.
"""

from __future__ import annotations

import psycopg

EDGE_TYPES = {"CALLS", "IMPORTS", "INHERITS", "DEFINES"}


def schema_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS graph_edges (
        repo      TEXT NOT NULL,
        from_id   TEXT NOT NULL,
        to_id     TEXT NOT NULL,
        edge_type TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS graph_edges_repo_idx ON graph_edges (repo);
    """


def init_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(schema_sql())
    conn.commit()


def replace_edges(conn: psycopg.Connection, repo: str, edges: list[tuple[str, str, str]]) -> None:
    """Delete `repo`'s existing edges and insert `edges` (full re-index, like code_chunks)."""
    for _, _, edge_type in edges:
        if edge_type not in EDGE_TYPES:
            raise ValueError(f"unknown edge type {edge_type!r}")

    with conn.cursor() as cur:
        cur.execute("DELETE FROM graph_edges WHERE repo = %s", (repo,))
        if edges:
            cur.executemany(
                "INSERT INTO graph_edges (repo, from_id, to_id, edge_type) VALUES (%s, %s, %s, %s)",
                [(repo, from_id, to_id, edge_type) for from_id, to_id, edge_type in edges],
            )
    conn.commit()


def get_edges(conn: psycopg.Connection, repo: str) -> list[tuple[str, str, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT from_id, to_id, edge_type FROM graph_edges WHERE repo = %s", (repo,))
        return [tuple(row) for row in cur.fetchall()]


def delete_repo(conn: psycopg.Connection, repo: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM graph_edges WHERE repo = %s", (repo,))
    conn.commit()
