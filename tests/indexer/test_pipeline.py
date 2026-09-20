from pathlib import Path

from src.indexer.pipeline import index_repo
from src.storage import db, graph_store

FIXTURES = Path(__file__).parents[2] / "fixtures"


class FakeEmbeddingClient:
    """Returns a fixed 3-dim vector, matching the test schema's embedding_dim."""

    def embed(self, texts: list[str], model: str, input_type: str) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_index_repo_summarizes_chunk_counts(pg_conn, tmp_path):
    summary = index_repo(
        FIXTURES / "simple_pkg", FakeEmbeddingClient(), pg_conn, repo_id="test-simple-pkg", graph_store_dir=tmp_path
    )

    assert summary.total_chunks == 12
    assert summary.functions == 3  # add, multiply, run
    assert summary.methods == 6
    assert summary.classes == 3  # Calculator, Animal, Dog
    assert summary.graph_nodes == 12 + 4  # chunks + modules (__init__, main, models, utils)
    assert summary.graph_edges > 0


def test_index_repo_stores_chunks_searchable_by_repo(pg_conn, tmp_path):
    index_repo(
        FIXTURES / "simple_pkg", FakeEmbeddingClient(), pg_conn, repo_id="test-simple-pkg", graph_store_dir=tmp_path
    )

    results = db.semantic_search(pg_conn, "test-simple-pkg", query_vector=[1.0, 0.0, 0.0], limit=100)

    assert len(results) == 12
    assert {r["qualified_name"] for r in results if r["kind"] == "class"} == {"Calculator", "Animal", "Dog"}


def test_index_repo_is_a_full_reindex_not_additive(pg_conn, tmp_path):
    index_repo(
        FIXTURES / "simple_pkg", FakeEmbeddingClient(), pg_conn, repo_id="test-simple-pkg", graph_store_dir=tmp_path
    )
    index_repo(
        FIXTURES / "simple_pkg", FakeEmbeddingClient(), pg_conn, repo_id="test-simple-pkg", graph_store_dir=tmp_path
    )

    results = db.semantic_search(pg_conn, "test-simple-pkg", query_vector=[1.0, 0.0, 0.0], limit=100)
    assert len(results) == 12  # re-indexing doesn't duplicate rows


def test_index_repo_persists_a_loadable_graph(pg_conn, tmp_path):
    index_repo(
        FIXTURES / "simple_pkg", FakeEmbeddingClient(), pg_conn, repo_id="test-simple-pkg", graph_store_dir=tmp_path
    )

    graph = graph_store.load_graph("test-simple-pkg", store_dir=tmp_path)

    assert graph.number_of_nodes() == 12 + 4
