from pathlib import Path

from src.indexer.embedder import ChunkEmbedding
from src.indexer.graph_builder import build_graph
from src.indexer.parser import parse_repo
from src.storage import db, graph_edges, repo_files
from src.storage.graph_reconstruction import edges_from_graph, reconstruct_graph

FIXTURES = Path(__file__).parents[2] / "fixtures" / "simple_pkg"


def _persist_fixture_graph(conn, repo: str):
    chunks = parse_repo(FIXTURES)
    embeddings = [ChunkEmbedding(chunk_id=c.id, vector=[1.0, 0.0, 0.0]) for c in chunks]
    db.upsert_chunks(conn, repo, chunks, embeddings)

    original_graph = build_graph(FIXTURES)
    graph_edges.replace_edges(conn, repo, edges_from_graph(original_graph))

    all_files = sorted({c.file for c in chunks} | {"__init__.py"})
    repo_files.replace_files(conn, repo, [(f, "") for f in all_files])

    return original_graph


def test_reconstruct_graph_matches_the_original_node_and_edge_counts(pg_conn):
    repo = "test-owner/simple_pkg@abc"
    original = _persist_fixture_graph(pg_conn, repo)

    rebuilt = reconstruct_graph(pg_conn, repo)

    assert rebuilt.number_of_nodes() == original.number_of_nodes()
    assert rebuilt.number_of_edges() == original.number_of_edges()


def test_reconstruct_graph_preserves_calls_edges_exactly(pg_conn):
    repo = "test-owner/simple_pkg@abc"
    original = _persist_fixture_graph(pg_conn, repo)

    rebuilt = reconstruct_graph(pg_conn, repo)

    def calls_by_qualified_name(graph):
        return {
            (graph.nodes[u]["qualified_name"], graph.nodes[v]["qualified_name"])
            for u, v, data in graph.edges(data=True)
            if data.get("type") == "CALLS"
        }

    assert calls_by_qualified_name(rebuilt) == calls_by_qualified_name(original)


def test_reconstruct_graph_includes_a_chunkless_module_like_init_py(pg_conn):
    repo = "test-owner/simple_pkg@abc"
    _persist_fixture_graph(pg_conn, repo)

    rebuilt = reconstruct_graph(pg_conn, repo)

    assert rebuilt.nodes["__init__.py"]["type"] == "module"


def test_reconstruct_graph_is_empty_for_an_unknown_repo(pg_conn):
    rebuilt = reconstruct_graph(pg_conn, "test-nonexistent/repo@zzz")

    assert rebuilt.number_of_nodes() == 0
    assert rebuilt.number_of_edges() == 0
