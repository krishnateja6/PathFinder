"""Derive a coarse architecture diagram from directory boundaries and
import relationships (spec section 3C) — deliberately NOT deep call-graph
clustering and NOT LLM-driven component labeling. Reuses
graph_builder.py's already-computed IMPORTS edges, aggregated up to the
directory level, so no new import-detection logic is needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

RECOMMENDED_MAX_COMPONENTS = 15
RECOMMENDED_MIN_COMPONENTS = 5


@dataclass(frozen=True)
class Component:
    id: str  # a directory path, or "(root)" for top-level files
    files: list[str]


@dataclass(frozen=True)
class ComponentEdge:
    source: str
    target: str
    import_count: int


@dataclass(frozen=True)
class ComponentGraph:
    components: list[Component]
    edges: list[ComponentEdge]

    def is_within_recommended_range(self) -> bool:
        return RECOMMENDED_MIN_COMPONENTS <= len(self.components) <= RECOMMENDED_MAX_COMPONENTS


def _component_of(file_path: str, depth: int) -> str:
    parts = file_path.split("/")[:-1]  # drop the filename itself
    if not parts:
        return "(root)"
    return "/".join(parts[:depth])


def derive_components(graph: nx.MultiDiGraph, depth: int = 1) -> ComponentGraph:
    """Group this repo's files into components by directory boundary
    (`depth` levels deep), with edges aggregated from the structural
    graph's IMPORTS edges between files in different components.
    """
    module_files = [node for node, data in graph.nodes(data=True) if data.get("type") == "module"]

    files_by_component: dict[str, list[str]] = {}
    component_of_file: dict[str, str] = {}
    for file_path in module_files:
        component = _component_of(file_path, depth)
        files_by_component.setdefault(component, []).append(file_path)
        component_of_file[file_path] = component

    edge_counts: dict[tuple[str, str], int] = {}
    for source_file, target_file, data in graph.edges(data=True):
        if data.get("type") != "IMPORTS":
            continue
        source_component = component_of_file.get(source_file)
        target_component = component_of_file.get(target_file)
        if source_component is None or target_component is None or source_component == target_component:
            continue
        key = (source_component, target_component)
        edge_counts[key] = edge_counts.get(key, 0) + 1

    components = [
        Component(id=component, files=sorted(files)) for component, files in sorted(files_by_component.items())
    ]
    edges = [
        ComponentEdge(source=source, target=target, import_count=count)
        for (source, target), count in sorted(edge_counts.items())
    ]

    return ComponentGraph(components=components, edges=edges)
