"""Parse Python source into function/class-level chunks using tree-sitter.

Each chunk keeps its signature, docstring, and body together (per the
spec's chunking strategy) rather than splitting on lines.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

PY_LANGUAGE = Language(tspython.language())

_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

_DEF_TYPES = {"function_definition", "class_definition"}


@dataclass(frozen=True)
class CodeChunk:
    """A single function, method, or class extracted from a source file."""

    id: str
    name: str
    qualified_name: str
    kind: str  # "function" | "method" | "class"
    file: str
    start_line: int
    end_line: int
    signature: str
    docstring: str | None
    source: str


def new_parser() -> Parser:
    return Parser(PY_LANGUAGE)


def iter_python_files(repo_root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(dirpath) / filename


def parse_repo(repo_root: Path) -> list[CodeChunk]:
    """Walk a repo and extract chunks from every Python file in it."""
    repo_root = Path(repo_root).resolve()
    parser = new_parser()
    chunks: list[CodeChunk] = []
    for file_path in sorted(iter_python_files(repo_root)):
        rel_path = file_path.relative_to(repo_root).as_posix()
        chunks.extend(parse_file(file_path, rel_path, parser=parser))
    return chunks


def parse_file(file_path: Path, rel_path: str, parser: Parser | None = None) -> list[CodeChunk]:
    """Extract chunks from a single Python file."""
    parser = parser or new_parser()
    source = Path(file_path).read_bytes()
    tree = parser.parse(source)
    chunks: list[CodeChunk] = []
    _walk(tree.root_node, scope_parts=[], parent_kind=None, rel_path=rel_path, source=source, chunks=chunks)
    return chunks


def _walk(
    node: Node,
    scope_parts: list[str],
    parent_kind: str | None,
    rel_path: str,
    source: bytes,
    chunks: list[CodeChunk],
) -> None:
    for child in node.named_children:
        outer_node = child
        def_node = child

        if child.type == "decorated_definition":
            inner = child.child_by_field_name("definition")
            if inner is None or inner.type not in _DEF_TYPES:
                continue
            def_node = inner
        elif child.type not in _DEF_TYPES:
            # Recurse into control-flow blocks (if/for/try/with, ...) since a
            # def nested inside one is still effectively at this scope level.
            if child.named_children:
                _walk(child, scope_parts, parent_kind, rel_path, source, chunks)
            continue

        name_node = def_node.child_by_field_name("name")
        name = name_node.text.decode("utf-8") if name_node is not None else "<anonymous>"
        qualified_name = ".".join([*scope_parts, name])

        if def_node.type == "class_definition":
            kind = "class"
        elif parent_kind == "class":
            kind = "method"
        else:
            kind = "function"

        chunks.append(_build_chunk(def_node, outer_node, name, qualified_name, kind, rel_path, source))

        body = def_node.child_by_field_name("body")
        if body is not None:
            if def_node.type == "class_definition":
                next_scope = [*scope_parts, name]
                next_kind = "class"
            else:
                next_scope = [*scope_parts, name, "<locals>"]
                next_kind = "function"
            _walk(body, next_scope, next_kind, rel_path, source, chunks)


def _build_chunk(
    def_node: Node,
    outer_node: Node,
    name: str,
    qualified_name: str,
    kind: str,
    rel_path: str,
    source: bytes,
) -> CodeChunk:
    start_line = outer_node.start_point[0] + 1
    end_line = outer_node.end_point[0] + 1
    chunk_id = f"{rel_path}::{qualified_name}:{start_line}"
    source_text = source[outer_node.start_byte : outer_node.end_byte].decode("utf-8")
    signature = _build_signature(def_node, outer_node, source)
    docstring = _extract_docstring(def_node, source)
    return CodeChunk(
        id=chunk_id,
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        file=rel_path,
        start_line=start_line,
        end_line=end_line,
        signature=signature,
        docstring=docstring,
        source=source_text,
    )


def _build_signature(def_node: Node, outer_node: Node, source: bytes) -> str:
    """The header (decorators + def/class line(s), up to the body) with no body text."""
    body = def_node.child_by_field_name("body")
    end_byte = body.start_byte if body is not None else def_node.end_byte
    text = source[outer_node.start_byte : end_byte].decode("utf-8")
    return text.rstrip()


def _extract_docstring(def_node: Node, source: bytes) -> str | None:
    body = def_node.child_by_field_name("body")
    if body is None or not body.named_children:
        return None
    first_stmt = body.named_children[0]
    if first_stmt.type != "expression_statement" or not first_stmt.named_children:
        return None
    string_node = first_stmt.named_children[0]
    if string_node.type != "string":
        return None
    return _string_content(string_node, source).strip()


def _string_content(string_node: Node, source: bytes) -> str:
    content_nodes = [c for c in string_node.children if c.type == "string_content"]
    if content_nodes:
        return "".join(source[c.start_byte : c.end_byte].decode("utf-8") for c in content_nodes)
    text = source[string_node.start_byte : string_node.end_byte].decode("utf-8")
    for quote in ('"""', "'''", '"', "'"):
        if text.startswith(quote) and text.endswith(quote) and len(text) >= 2 * len(quote):
            return text[len(quote) : -len(quote)]
    return text
