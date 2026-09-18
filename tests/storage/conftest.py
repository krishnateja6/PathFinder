import psycopg
import pytest

from src.storage import db


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
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM code_chunks WHERE repo LIKE 'test-%'")
        conn.commit()
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM code_chunks WHERE repo LIKE 'test-%'")
        conn.commit()
        conn.close()
