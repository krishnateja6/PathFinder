import pytest

from src.ingestion.github_client import RepoMetadata
from src.ingestion.pipeline import analyze_github_repo
from src.storage import analyses, db, repo_files
from src.storage.graph_reconstruction import reconstruct_graph

METADATA = RepoMetadata(owner="acme", repo="widget", default_branch="main", commit_sha="deadbeef1234567890", size_kb=10)

FILES = [
    ("main.py", b"from .utils import add\n\ndef run():\n    return add(1, 2)\n"),
    ("utils.py", b"def add(a, b):\n    return a + b\n"),
    ("README.md", b"# Test Repo\nSome description.\n"),
]


class FakeGitHubClient:
    def __init__(self, metadata=METADATA, files=None):
        self._metadata = metadata
        self._files = files if files is not None else FILES
        self.download_calls = 0

    def get_repo_metadata(self, owner, repo):
        return self._metadata

    def download_source_files(self, owner, repo, commit_sha):
        self.download_calls += 1
        return self._files


class FakeEmbeddingClient:
    def embed(self, texts, model, input_type):
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_analyze_github_repo_persists_chunks_edges_and_files(pg_conn):
    summary = analyze_github_repo(
        "https://github.com/test-acme/widget", pg_conn, FakeEmbeddingClient(), FakeGitHubClient()
    )

    assert summary.cached is False
    assert summary.repo_key == "test-acme/widget"
    assert summary.commit_sha == "deadbeef1234567890"
    assert summary.repo_id == "test-acme/widget@deadbeef1234"
    assert summary.file_count == 3
    assert summary.chunk_count == 3  # run, add, + one generic README.md chunk

    stored = db.get_chunks_by_repo(pg_conn, summary.repo_id)
    assert {c["qualified_name"] for c in stored} == {"run", "add", "README.md:1-2"}

    assert repo_files.get_file(pg_conn, summary.repo_id, "utils.py") == "def add(a, b):\n    return a + b\n"

    record = analyses.get_analysis(pg_conn, "test-acme/widget", "deadbeef1234567890")
    assert record.status == "ready"
    assert record.chunk_count == 3


def test_analyze_github_repo_produces_a_correct_calls_edge(pg_conn):
    summary = analyze_github_repo(
        "https://github.com/test-acme/widget", pg_conn, FakeEmbeddingClient(), FakeGitHubClient()
    )

    graph = reconstruct_graph(pg_conn, summary.repo_id)

    run_id = next(n for n, d in graph.nodes(data=True) if d.get("qualified_name") == "run")
    add_id = next(n for n, d in graph.nodes(data=True) if d.get("qualified_name") == "add")
    assert graph.has_edge(run_id, add_id)


def test_analyze_github_repo_is_cached_on_second_call(pg_conn):
    client = FakeGitHubClient()

    first = analyze_github_repo("https://github.com/test-acme/widget", pg_conn, FakeEmbeddingClient(), client)
    second = analyze_github_repo("https://github.com/test-acme/widget", pg_conn, FakeEmbeddingClient(), client)

    assert first.cached is False
    assert second.cached is True
    assert client.download_calls == 1  # not re-downloaded/re-parsed/re-embedded


def test_analyze_github_repo_reports_progress_stages(pg_conn):
    stages = []

    analyze_github_repo(
        "https://github.com/test-acme/widget",
        pg_conn,
        FakeEmbeddingClient(),
        FakeGitHubClient(),
        on_progress=stages.append,
    )

    assert stages == ["validating", "fetching", "scanning", "parsing", "embedding", "persisting", "ready"]


def test_analyze_github_repo_cached_path_reports_short_stage_list(pg_conn):
    client = FakeGitHubClient()
    analyze_github_repo("https://github.com/test-acme/widget", pg_conn, FakeEmbeddingClient(), client)

    stages = []
    analyze_github_repo(
        "https://github.com/test-acme/widget", pg_conn, FakeEmbeddingClient(), client, on_progress=stages.append
    )

    assert stages == ["validating", "fetching", "cached"]


def test_analyze_github_repo_marks_analysis_failed_on_error(pg_conn):
    class FailingGitHubClient(FakeGitHubClient):
        def download_source_files(self, owner, repo, commit_sha):
            raise RuntimeError("network exploded")

    with pytest.raises(RuntimeError, match="network exploded"):
        analyze_github_repo(
            "https://github.com/test-acme/widget", pg_conn, FakeEmbeddingClient(), FailingGitHubClient()
        )

    record = analyses.get_analysis(pg_conn, "test-acme/widget", "deadbeef1234567890")
    assert record.status == "failed"
    assert "network exploded" in record.error_message


def test_analyze_github_repo_rejects_an_oversized_repo(pg_conn):
    huge_files = [(f"f{i}.py", b"x" * 10) for i in range(1000)]
    client = FakeGitHubClient(files=huge_files)

    from src.ingestion.source_filter import RepoTooLargeError

    with pytest.raises(RepoTooLargeError):
        analyze_github_repo("https://github.com/test-acme/widget", pg_conn, FakeEmbeddingClient(), client)

    record = analyses.get_analysis(pg_conn, "test-acme/widget", "deadbeef1234567890")
    assert record.status == "failed"


class CountingEmbeddingClient:
    """Like FakeEmbeddingClient, but records every text it was asked to embed."""

    def __init__(self):
        self.embedded_texts: list[str] = []

    def embed(self, texts, model, input_type):
        self.embedded_texts.extend(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_reanalyzing_a_new_commit_only_reembeds_changed_chunks(pg_conn):
    """spec: "don't re-embed unchanged files" — utils.py is untouched
    between commits, so its chunk's embedding should be copied forward,
    not recomputed."""
    embedding_client = CountingEmbeddingClient()
    first_client = FakeGitHubClient()
    analyze_github_repo("https://github.com/test-acme/widget", pg_conn, embedding_client, first_client)
    first_call_count = len(embedding_client.embedded_texts)
    assert first_call_count == 3  # run, add, README chunk

    new_metadata = RepoMetadata(
        owner="acme", repo="widget", default_branch="main", commit_sha="cafebabe1234567890", size_kb=10
    )
    changed_files = [
        ("main.py", b"from .utils import add\n\ndef run():\n    return add(3, 4)\n"),  # changed
        ("utils.py", b"def add(a, b):\n    return a + b\n"),  # unchanged
        ("README.md", b"# Test Repo\nSome description.\n"),  # unchanged
    ]
    second_client = FakeGitHubClient(metadata=new_metadata, files=changed_files)

    summary = analyze_github_repo("https://github.com/test-acme/widget", pg_conn, embedding_client, second_client)

    assert summary.cached is False
    assert summary.chunk_count == 3
    newly_embedded = embedding_client.embedded_texts[first_call_count:]
    assert len(newly_embedded) == 1  # only run() changed
    assert "return add(3, 4)" in newly_embedded[0]

    # and the reused embedding actually made it into storage, unchanged
    stored = db.get_chunk_sources_and_embeddings(pg_conn, summary.repo_id)
    add_id = next(cid for cid, (source, _vec) in stored.items() if "def add" in source)
    assert stored[add_id][1] == [1.0, 0.0, 0.0]
