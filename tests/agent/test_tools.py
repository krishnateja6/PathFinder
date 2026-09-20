from pathlib import Path

import pytest

from src.agent import tools
from src.agent.tools import AgentContext
from src.indexer.embedder import ChunkEmbedding
from src.indexer.graph_builder import build_graph
from src.indexer.parser import parse_repo
from src.storage import db

FIXTURES = Path(__file__).parents[2] / "fixtures"


class FakeEmbeddingClient:
    def embed(self, texts: list[str], model: str, input_type: str) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def ctx(pg_conn) -> AgentContext:
    repo_root = FIXTURES / "simple_pkg"
    repo_id = "test-agent-tools"

    chunks = parse_repo(repo_root)
    embeddings = [ChunkEmbedding(chunk_id=c.id, vector=[1.0, 0.0, 0.0]) for c in chunks]
    db.upsert_chunks(pg_conn, repo_id, chunks, embeddings)

    graph = build_graph(repo_root)

    return AgentContext(
        repo_root=repo_root,
        repo_id=repo_id,
        conn=pg_conn,
        embedding_client=FakeEmbeddingClient(),
        graph=graph,
    )


def test_semantic_search_returns_indexed_chunks(ctx):
    results = tools.semantic_search(ctx, "calculator arithmetic", limit=5)

    assert len(results) == 5
    assert {r["qualified_name"] for r in results} <= {
        c.qualified_name for c in parse_repo(FIXTURES / "simple_pkg")
    }


def test_read_file_returns_requested_line_range(ctx):
    result = tools.read_file(ctx, "utils.py", start_line=1, end_line=6)

    assert result["path"] == "utils.py"
    assert result["start_line"] == 1
    assert result["end_line"] == 6
    assert "def add" in result["content"]


def test_read_file_rejects_paths_outside_the_repo(ctx):
    result = tools.read_file(ctx, "../../etc/passwd")

    assert "error" in result


def test_read_file_reports_missing_file(ctx):
    result = tools.read_file(ctx, "does_not_exist.py")

    assert "error" in result


def test_find_definition_locates_a_class(ctx):
    results = tools.find_definition(ctx, "Calculator")

    assert len(results) == 1
    assert results[0]["kind"] == "class"
    assert results[0]["file"] == "utils.py"


def test_find_callees_of_run_matches_hand_derived_graph(ctx):
    results = tools.find_callees(ctx, "run")

    assert {r["qualified_name"] for r in results} == {
        "Calculator.__init__",
        "Calculator.add",
        "add",
        "Animal.__init__",
        "Dog.speak",
    }


def test_find_callers_of_a_qualified_method(ctx):
    results = tools.find_callers(ctx, "Calculator.add")

    assert {r["qualified_name"] for r in results} == {"run"}


def test_find_callers_and_callees_empty_for_unknown_symbol(ctx):
    assert tools.find_callers(ctx, "nonexistent_symbol") == []
    assert tools.find_callees(ctx, "nonexistent_symbol") == []
