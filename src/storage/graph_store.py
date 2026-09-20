"""Persist a repo's networkx graph to disk, keyed by repo_id.

v1 storage per the spec: pickle to disk rather than a graph DB — the
graph is small enough (single-repo scale) that in-memory + file
persistence is sufficient.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import networkx as nx

DEFAULT_STORE_DIR = Path(".codeintel") / "graphs"


def _safe_key(repo_id: str) -> str:
    return repo_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def graph_path(repo_id: str, store_dir: Path | None = None) -> Path:
    store_dir = store_dir if store_dir is not None else DEFAULT_STORE_DIR
    return store_dir / f"{_safe_key(repo_id)}.pkl"


def save_graph(graph: nx.MultiDiGraph, repo_id: str, store_dir: Path | None = None) -> Path:
    path = graph_path(repo_id, store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(graph, f)
    return path


def load_graph(repo_id: str, store_dir: Path | None = None) -> nx.MultiDiGraph:
    path = graph_path(repo_id, store_dir)
    with path.open("rb") as f:
        return pickle.load(f)


def has_graph(repo_id: str, store_dir: Path | None = None) -> bool:
    return graph_path(repo_id, store_dir).exists()
