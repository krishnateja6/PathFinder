import psycopg
import pytest

from src.storage import analyses, db, graph_edges, repo_files


def _clean_test_rows(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM code_chunks WHERE repo LIKE 'test-%'")
        cur.execute("DELETE FROM analyses WHERE repo_key LIKE 'test-%'")
        cur.execute("DELETE FROM graph_edges WHERE repo LIKE 'test-%'")
        cur.execute("DELETE FROM repo_files WHERE repo LIKE 'test-%'")
    conn.commit()


@pytest.fixture
def pg_conn():
    """A real connection to a scratch Postgres+pgvector, skipped if unreachable.

    Local dev: `docker compose up -d`. CI: a postgres service container
    (see .github/workflows/ci.yml) is always reachable.
    """
    try:
        conn = db.connect()
    except psycopg.OperationalError as exc:
        pytest.skip(f"no reachable Postgres for storage tests: {exc}")
        return

    db.init_schema(conn, embedding_dim=3)
    analyses.init_schema(conn)
    graph_edges.init_schema(conn)
    repo_files.init_schema(conn)
    try:
        _clean_test_rows(conn)
        yield conn
    finally:
        _clean_test_rows(conn)
        conn.close()
