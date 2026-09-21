"""Postgres + pgvector storage for the semantic index.

Local dev DB is the one in docker-compose.yml; DATABASE_URL overrides it.
"""

from __future__ import annotations

import os

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from src.indexer.embedder import ChunkEmbedding
from src.indexer.parser import CodeChunk

DEFAULT_DSN = "postgresql://codeintel:codeintel@localhost:5432/codeintel"

# voyage-code-2 embeds to 1536 dimensions. If the embedding model changes,
# this must change (and the table recreated) to match.
DEFAULT_EMBEDDING_DIM = 1536


def get_dsn() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DSN)


def connect(dsn: str | None = None) -> psycopg.Connection:
    """Connect and register the pgvector type, if the extension is already installed.

    On a brand-new database the `vector` extension doesn't exist yet, so
    registration is retried after `init_schema` creates it.
    """
    conn = psycopg.connect(dsn or get_dsn())
    _try_register_vector(conn)
    return conn


def _try_register_vector(conn: psycopg.Connection) -> None:
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        conn.rollback()


def schema_sql(embedding_dim: int = DEFAULT_EMBEDDING_DIM) -> str:
    return f"""
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS code_chunks (
        id TEXT NOT NULL,
        repo TEXT NOT NULL,
        name TEXT NOT NULL,
        qualified_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        file TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        signature TEXT NOT NULL,
        docstring TEXT,
        source TEXT NOT NULL,
        embedding VECTOR({embedding_dim}),
        PRIMARY KEY (repo, id)
    );

    CREATE INDEX IF NOT EXISTS code_chunks_repo_idx ON code_chunks (repo);
    """


def init_schema(conn: psycopg.Connection, embedding_dim: int = DEFAULT_EMBEDDING_DIM) -> None:
    with conn.cursor() as cur:
        cur.execute(schema_sql(embedding_dim))
    conn.commit()
    _try_register_vector(conn)


def upsert_chunks(
    conn: psycopg.Connection,
    repo: str,
    chunks: list[CodeChunk],
    embeddings: list[ChunkEmbedding],
) -> None:
    """Insert or update chunks for `repo`, keyed by (repo, chunk id).

    Keyed on the pair, not id alone: two different repos can easily
    produce the same relative chunk id (e.g. both have a utils.py::add
    at the same line), and id-only conflict resolution would let one
    repo's row silently overwrite another's.
    """
    vectors_by_id = {e.chunk_id: Vector(e.vector) for e in embeddings}
    rows = [
        (
            chunk.id,
            repo,
            chunk.name,
            chunk.qualified_name,
            chunk.kind,
            chunk.file,
            chunk.start_line,
            chunk.end_line,
            chunk.signature,
            chunk.docstring,
            chunk.source,
            vectors_by_id.get(chunk.id),
        )
        for chunk in chunks
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO code_chunks
                (id, repo, name, qualified_name, kind, file, start_line, end_line,
                 signature, docstring, source, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo, id) DO UPDATE SET
                name = EXCLUDED.name,
                qualified_name = EXCLUDED.qualified_name,
                kind = EXCLUDED.kind,
                file = EXCLUDED.file,
                start_line = EXCLUDED.start_line,
                end_line = EXCLUDED.end_line,
                signature = EXCLUDED.signature,
                docstring = EXCLUDED.docstring,
                source = EXCLUDED.source,
                embedding = EXCLUDED.embedding
            """,
            rows,
        )
    conn.commit()


def delete_repo(conn: psycopg.Connection, repo: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM code_chunks WHERE repo = %s", (repo,))
    conn.commit()


def get_chunks_by_repo(conn: psycopg.Connection, repo: str) -> list[dict]:
    """Every chunk for `repo`, unfiltered by any vector similarity — used to
    reconstruct the full structural graph, not for semantic search."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, qualified_name, kind, file, start_line, end_line, signature, docstring
            FROM code_chunks
            WHERE repo = %s
            """,
            (repo,),
        )
        assert cur.description is not None
        columns = [desc.name for desc in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def get_chunk_sources_and_embeddings(conn: psycopg.Connection, repo: str) -> dict[str, tuple[str, list[float]]]:
    """chunk id -> (source, embedding) for `repo` — lets a re-analysis reuse
    an unchanged chunk's existing embedding instead of paying to re-embed
    identical content (spec's "don't re-embed unchanged files")."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, source, embedding FROM code_chunks WHERE repo = %s", (repo,))
        return {row[0]: (row[1], row[2].to_list()) for row in cur.fetchall() if row[2] is not None}


def semantic_search(
    conn: psycopg.Connection,
    repo: str,
    query_vector: list[float],
    limit: int = 10,
) -> list[dict]:
    """Nearest chunks to `query_vector` by cosine distance, within `repo`."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, qualified_name, kind, file, start_line, end_line,
                   signature, docstring, embedding <=> %(query_vector)s AS distance
            FROM code_chunks
            WHERE repo = %(repo)s
            ORDER BY distance ASC
            LIMIT %(limit)s
            """,
            {"query_vector": Vector(query_vector), "repo": repo, "limit": limit},
        )
        assert cur.description is not None
        columns = [desc.name for desc in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
