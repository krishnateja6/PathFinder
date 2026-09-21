"""The `analyses` table: caching/session lookup for repo-analysis runs.

Keyed by (repo_key, commit_sha) so re-submitting an already-analyzed
commit is a cache hit rather than a re-run of the full ingestion
pipeline (spec section 3B). `repo_key` is "owner/repo"; the rest of the
storage layer (code_chunks.repo, graph_edges.repo, repo_files.repo)
uses the composite "owner/repo@shortsha" string built by `repo_id()`.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

VALID_STATUSES = {"pending", "ready", "failed"}
SHORT_SHA_LENGTH = 12


def repo_key(owner: str, repo: str) -> str:
    return f"{owner}/{repo}"


def repo_id(owner: str, repo: str, commit_sha: str) -> str:
    """The composite key used everywhere a repo-scoped storage row is written."""
    return f"{owner}/{repo}@{commit_sha[:SHORT_SHA_LENGTH]}"


@dataclass(frozen=True)
class Analysis:
    repo_key: str
    commit_sha: str
    status: str
    default_branch: str | None
    file_count: int | None
    chunk_count: int | None
    error_message: str | None


def schema_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS analyses (
        repo_key        TEXT NOT NULL,
        commit_sha      TEXT NOT NULL,
        status          TEXT NOT NULL,
        default_branch  TEXT,
        file_count      INTEGER,
        chunk_count     INTEGER,
        error_message   TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (repo_key, commit_sha)
    );

    CREATE INDEX IF NOT EXISTS analyses_repo_key_idx ON analyses (repo_key, created_at DESC);
    """


def init_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(schema_sql())
    conn.commit()


def upsert_analysis(
    conn: psycopg.Connection,
    repo_key: str,
    commit_sha: str,
    status: str,
    default_branch: str | None = None,
    file_count: int | None = None,
    chunk_count: int | None = None,
    error_message: str | None = None,
) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}, must be one of {sorted(VALID_STATUSES)}")

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analyses
                (repo_key, commit_sha, status, default_branch, file_count, chunk_count, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo_key, commit_sha) DO UPDATE SET
                status = EXCLUDED.status,
                default_branch = EXCLUDED.default_branch,
                file_count = EXCLUDED.file_count,
                chunk_count = EXCLUDED.chunk_count,
                error_message = EXCLUDED.error_message
            """,
            (repo_key, commit_sha, status, default_branch, file_count, chunk_count, error_message),
        )
    conn.commit()


def get_analysis(conn: psycopg.Connection, repo_key: str, commit_sha: str) -> Analysis | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT repo_key, commit_sha, status, default_branch, file_count, chunk_count, error_message
            FROM analyses
            WHERE repo_key = %s AND commit_sha = %s
            """,
            (repo_key, commit_sha),
        )
        row = cur.fetchone()
    return Analysis(*row) if row else None


def get_latest_ready_analysis(conn: psycopg.Connection, repo_key: str) -> Analysis | None:
    """The most recently indexed *ready* analysis for a repo, regardless of commit."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT repo_key, commit_sha, status, default_branch, file_count, chunk_count, error_message
            FROM analyses
            WHERE repo_key = %s AND status = 'ready'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (repo_key,),
        )
        row = cur.fetchone()
    return Analysis(*row) if row else None
