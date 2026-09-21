"""Orchestrates the full GitHub-repo analysis pipeline: validate → fetch
metadata → check cache → download → filter → parse/chunk → embed →
persist (chunks, graph edges, files, analysis record).

The GitHub-repo sibling of src/indexer/pipeline.py's index_repo(), which
does the same thing for a local path already on disk. Downloaded bytes
are materialized into a temp directory so parser.py/graph_builder.py can
run completely unchanged against them.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg

from src.indexer.embedder import ChunkEmbedding, EmbeddingClient, embed_chunks
from src.indexer.generic_chunker import chunk_file
from src.indexer.graph_builder import build_graph
from src.indexer.parser import CodeChunk, parse_repo
from src.indexer.tech_stack import TechStack, detect_tech_stack
from src.ingestion.github_client import GitHubClient
from src.ingestion.source_filter import filter_source_files
from src.ingestion.validator import parse_github_url
from src.storage import analyses, db, graph_edges, repo_files
from src.storage.graph_reconstruction import edges_from_graph

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class AnalysisSummary:
    repo_key: str
    commit_sha: str
    repo_id: str
    cached: bool
    file_count: int
    chunk_count: int
    tech_stack: TechStack


def _report(on_progress: ProgressCallback | None, stage: str) -> None:
    if on_progress is not None:
        on_progress(stage)


def _decode_text(content: bytes) -> str | None:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _embed_reusing_unchanged_chunks(
    conn: psycopg.Connection,
    owner: str,
    repo: str,
    chunks: list[CodeChunk],
    embedding_client: EmbeddingClient,
) -> list[ChunkEmbedding]:
    """Only pay to embed chunks whose source actually changed since this
    repo's last analyzed commit — a chunk with the same id and identical
    source text gets its previous embedding copied forward instead.
    """
    if not chunks:
        return []

    previous = analyses.get_latest_ready_analysis(conn, analyses.repo_key(owner, repo))
    previous_data: dict[str, tuple[str, list[float]]] = {}
    if previous is not None:
        previous_repo_id = analyses.repo_id(owner, repo, previous.commit_sha)
        previous_data = db.get_chunk_sources_and_embeddings(conn, previous_repo_id)

    to_embed: list[CodeChunk] = []
    reused: list[ChunkEmbedding] = []
    for chunk in chunks:
        old = previous_data.get(chunk.id)
        if old is not None and old[0] == chunk.source:
            reused.append(ChunkEmbedding(chunk_id=chunk.id, vector=old[1]))
        else:
            to_embed.append(chunk)

    fresh = embed_chunks(to_embed, embedding_client) if to_embed else []
    return fresh + reused


def analyze_github_repo(
    github_url: str,
    conn: psycopg.Connection,
    embedding_client: EmbeddingClient,
    github_client: GitHubClient,
    on_progress: ProgressCallback | None = None,
) -> AnalysisSummary:
    """Analyze a public GitHub repo, or return the cached result for its
    current commit if it's already been analyzed."""
    _report(on_progress, "validating")
    owner, repo = parse_github_url(github_url)

    _report(on_progress, "fetching")
    metadata = github_client.get_repo_metadata(owner, repo)
    key = analyses.repo_key(owner, repo)
    rid = analyses.repo_id(owner, repo, metadata.commit_sha)

    cached = analyses.get_analysis(conn, key, metadata.commit_sha)
    if cached is not None and cached.status == "ready":
        _report(on_progress, "cached")
        return AnalysisSummary(
            repo_key=key,
            commit_sha=metadata.commit_sha,
            repo_id=rid,
            cached=True,
            file_count=cached.file_count or 0,
            chunk_count=cached.chunk_count or 0,
            tech_stack=TechStack(),
        )

    analyses.upsert_analysis(conn, key, metadata.commit_sha, status="pending", default_branch=metadata.default_branch)

    try:
        _report(on_progress, "scanning")
        raw_files = github_client.download_source_files(owner, repo, metadata.commit_sha)
        filtered = filter_source_files(raw_files)

        _report(on_progress, "parsing")
        all_chunks: list[CodeChunk] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            has_python = False
            for path, content in filtered.files:
                if not path.endswith(".py"):
                    continue
                text = _decode_text(content)
                if text is None:
                    continue
                full_path = tmp_path / path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(text)
                has_python = True

            all_chunks.extend(parse_repo(tmp_path) if has_python else [])
            graph = build_graph(tmp_path)

            for path, content in filtered.files:
                if path.endswith(".py"):
                    continue
                text = _decode_text(content)
                if text is None:
                    continue
                all_chunks.extend(chunk_file(path, text))

        _report(on_progress, "embedding")
        embeddings = _embed_reusing_unchanged_chunks(conn, owner, repo, all_chunks, embedding_client)

        _report(on_progress, "persisting")
        db.init_schema(conn)
        db.delete_repo(conn, rid)
        db.upsert_chunks(conn, rid, all_chunks, embeddings)
        graph_edges.replace_edges(conn, rid, edges_from_graph(graph))

        text_files = []
        for path, content in filtered.files:
            text = _decode_text(content)
            if text is not None:
                text_files.append((path, text))
        repo_files.replace_files(conn, rid, text_files)

        tech_stack = detect_tech_stack([path for path, _ in filtered.files])

        analyses.upsert_analysis(
            conn,
            key,
            metadata.commit_sha,
            status="ready",
            default_branch=metadata.default_branch,
            file_count=len(filtered.files),
            chunk_count=len(all_chunks),
        )
        _report(on_progress, "ready")

        return AnalysisSummary(
            repo_key=key,
            commit_sha=metadata.commit_sha,
            repo_id=rid,
            cached=False,
            file_count=len(filtered.files),
            chunk_count=len(all_chunks),
            tech_stack=tech_stack,
        )
    except Exception as exc:
        analyses.upsert_analysis(
            conn, key, metadata.commit_sha, status="failed", default_branch=metadata.default_branch, error_message=str(exc)
        )
        raise
