"""Generic, language-agnostic chunking for non-Python source files.

Whole-file if small, else fixed-size line windows. These chunks feed the
same embed_chunks()/upsert_chunks() pipeline as Python CodeChunks, so
they're searchable via semantic_search — but they never appear in the
call/import graph (only parser.py's Python-specific walk produces graph
nodes), so find_definition/find_callers/find_callees and impact analysis
correctly have nothing to say about them. This is what makes "full
structural analysis vs. semantic-search-only" (spec section 3D) a real,
visible distinction instead of a moot one.
"""

from __future__ import annotations

from src.indexer.parser import CodeChunk

DEFAULT_WINDOW_LINES = 200
KIND = "file_chunk"


def chunk_file(rel_path: str, content: str, window_lines: int = DEFAULT_WINDOW_LINES) -> list[CodeChunk]:
    """Split `content` into one or more fixed-size line-window chunks."""
    lines = content.splitlines()
    if not lines:
        return []

    name = rel_path.rsplit("/", 1)[-1]
    chunks: list[CodeChunk] = []
    for start in range(0, len(lines), window_lines):
        window = lines[start : start + window_lines]
        start_line = start + 1
        end_line = start + len(window)
        qualified_name = f"{rel_path}:{start_line}-{end_line}"
        chunks.append(
            CodeChunk(
                id=f"{rel_path}::{start_line}-{end_line}",
                name=name,
                qualified_name=qualified_name,
                kind=KIND,
                file=rel_path,
                start_line=start_line,
                end_line=end_line,
                signature=f"# {rel_path} (lines {start_line}-{end_line})",
                docstring=None,
                source="\n".join(window),
            )
        )
    return chunks
