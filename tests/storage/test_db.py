from src.indexer.embedder import ChunkEmbedding
from src.indexer.parser import CodeChunk
from src.storage import db


def test_schema_sql_creates_pgvector_extension_and_table_with_given_dim():
    sql = db.schema_sql(embedding_dim=1536)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE TABLE IF NOT EXISTS code_chunks" in sql
    assert "VECTOR(1536)" in sql


def make_chunk(chunk_id: str, name: str, file: str = "mod.py") -> CodeChunk:
    return CodeChunk(
        id=chunk_id,
        name=name,
        qualified_name=name,
        kind="function",
        file=file,
        start_line=1,
        end_line=2,
        signature=f"def {name}():",
        docstring="a doc.",
        source=f"def {name}():\n    pass",
    )


def test_upsert_and_semantic_search_roundtrip(pg_conn):
    repo = "test-repo"
    chunks = [
        make_chunk("mod.py::near:1", "near"),
        make_chunk("mod.py::far:5", "far"),
    ]
    embeddings = [
        ChunkEmbedding(chunk_id="mod.py::near:1", vector=[1.0, 0.0, 0.0]),
        ChunkEmbedding(chunk_id="mod.py::far:5", vector=[0.0, 1.0, 0.0]),
    ]

    db.upsert_chunks(pg_conn, repo, chunks, embeddings)
    results = db.semantic_search(pg_conn, repo, query_vector=[1.0, 0.0, 0.0], limit=5)

    assert [r["id"] for r in results] == ["mod.py::near:1", "mod.py::far:5"]
    assert results[0]["qualified_name"] == "near"


def test_semantic_search_is_scoped_to_repo(pg_conn):
    chunk = make_chunk("mod.py::foo:1", "foo")
    embedding = [ChunkEmbedding(chunk_id=chunk.id, vector=[1.0, 0.0, 0.0])]

    db.upsert_chunks(pg_conn, "test-repo-a", [chunk], embedding)

    results = db.semantic_search(pg_conn, "test-repo-b", query_vector=[1.0, 0.0, 0.0], limit=5)

    assert results == []


def test_upsert_updates_existing_chunk_by_id(pg_conn):
    repo = "test-repo"
    chunk = make_chunk("mod.py::foo:1", "foo")
    embedding = [ChunkEmbedding(chunk_id=chunk.id, vector=[1.0, 0.0, 0.0])]
    db.upsert_chunks(pg_conn, repo, [chunk], embedding)

    updated_chunk = make_chunk("mod.py::foo:1", "foo_renamed")
    db.upsert_chunks(pg_conn, repo, [updated_chunk], embedding)

    results = db.semantic_search(pg_conn, repo, query_vector=[1.0, 0.0, 0.0], limit=5)
    assert len(results) == 1
    assert results[0]["qualified_name"] == "foo_renamed"


def test_upsert_chunks_with_the_same_id_in_different_repos_do_not_collide(pg_conn):
    """Regression test: code_chunks used to be keyed by id alone, so two
    different repos sharing a relative chunk id (very plausible — the same
    file/function/line shape is common) would silently overwrite each
    other. The primary key is now (repo, id)."""
    shared_id = "mod.py::add:4"
    chunk_a = make_chunk(shared_id, "add_from_repo_a")
    chunk_b = make_chunk(shared_id, "add_from_repo_b")
    vec = [1.0, 0.0, 0.0]

    db.upsert_chunks(pg_conn, "test-repo-a", [chunk_a], [ChunkEmbedding(shared_id, vec)])
    db.upsert_chunks(pg_conn, "test-repo-b", [chunk_b], [ChunkEmbedding(shared_id, vec)])

    results_a = db.semantic_search(pg_conn, "test-repo-a", vec, limit=5)
    results_b = db.semantic_search(pg_conn, "test-repo-b", vec, limit=5)

    assert [r["qualified_name"] for r in results_a] == ["add_from_repo_a"]
    assert [r["qualified_name"] for r in results_b] == ["add_from_repo_b"]


def test_get_chunks_by_repo_returns_everything_regardless_of_similarity(pg_conn):
    chunk_a = make_chunk("mod.py::a:1", "a")
    chunk_b = make_chunk("mod.py::b:5", "b")
    db.upsert_chunks(
        pg_conn,
        "test-repo",
        [chunk_a, chunk_b],
        [ChunkEmbedding("mod.py::a:1", [1.0, 0.0, 0.0]), ChunkEmbedding("mod.py::b:5", [0.0, 1.0, 0.0])],
    )

    results = db.get_chunks_by_repo(pg_conn, "test-repo")

    assert {r["qualified_name"] for r in results} == {"a", "b"}
    assert "embedding" not in results[0]


def test_get_chunk_sources_and_embeddings_round_trips_the_vector(pg_conn):
    chunk = make_chunk("mod.py::a:1", "a")
    db.upsert_chunks(pg_conn, "test-repo", [chunk], [ChunkEmbedding("mod.py::a:1", [1.0, 2.0, 3.0])])

    result = db.get_chunk_sources_and_embeddings(pg_conn, "test-repo")

    assert result["mod.py::a:1"] == (chunk.source, [1.0, 2.0, 3.0])


def test_get_chunk_sources_and_embeddings_scoped_by_repo(pg_conn):
    chunk = make_chunk("mod.py::a:1", "a")
    db.upsert_chunks(pg_conn, "test-repo-a", [chunk], [ChunkEmbedding("mod.py::a:1", [1.0, 0.0, 0.0])])

    assert db.get_chunk_sources_and_embeddings(pg_conn, "test-repo-b") == {}


def test_delete_repo_removes_only_that_repos_chunks(pg_conn):
    chunk_a = make_chunk("mod.py::a:1", "a")
    chunk_b = make_chunk("mod.py::b:1", "b")
    embedding_vec = [1.0, 0.0, 0.0]
    db.upsert_chunks(pg_conn, "test-repo-a", [chunk_a], [ChunkEmbedding(chunk_a.id, embedding_vec)])
    db.upsert_chunks(pg_conn, "test-repo-b", [chunk_b], [ChunkEmbedding(chunk_b.id, embedding_vec)])

    db.delete_repo(pg_conn, "test-repo-a")

    assert db.semantic_search(pg_conn, "test-repo-a", embedding_vec) == []
    assert len(db.semantic_search(pg_conn, "test-repo-b", embedding_vec)) == 1
