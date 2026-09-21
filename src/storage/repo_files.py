"""Raw file content storage for the web product.

The Explorer tab and the Postgres-backed `read_file` tool variant both
need to read a file's full content on a *later* request than the one
that ingested it — and serverless functions have no persistent disk to
re-read from between invocations. This table is that persistence.
"""

from __future__ import annotations

import psycopg


def schema_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS repo_files (
        repo    TEXT NOT NULL,
        path    TEXT NOT NULL,
        content TEXT NOT NULL,
        PRIMARY KEY (repo, path)
    );
    """


def init_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(schema_sql())
    conn.commit()


def replace_files(conn: psycopg.Connection, repo: str, files: list[tuple[str, str]]) -> None:
    """Delete `repo`'s existing files and insert `files` (full re-index)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM repo_files WHERE repo = %s", (repo,))
        if files:
            cur.executemany(
                "INSERT INTO repo_files (repo, path, content) VALUES (%s, %s, %s)",
                [(repo, path, content) for path, content in files],
            )
    conn.commit()


def get_file(conn: psycopg.Connection, repo: str, path: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT content FROM repo_files WHERE repo = %s AND path = %s", (repo, path))
        row = cur.fetchone()
    return row[0] if row else None


def list_paths(conn: psycopg.Connection, repo: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT path FROM repo_files WHERE repo = %s ORDER BY path", (repo,))
        return [row[0] for row in cur.fetchall()]


def delete_repo(conn: psycopg.Connection, repo: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM repo_files WHERE repo = %s", (repo,))
    conn.commit()
