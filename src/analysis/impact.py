"""Change-impact analysis: graph traversal from a symbol to everything
downstream that depends on it (spec §3.3). Pure graph algorithm, no LLM.

"Depends on" means: transitively calls it (CALLS edges, reversed), or
— for a class — transitively inherits from it (INHERITS edges,
reversed). Changing a class is treated as changing all of its own
methods too, so a class's impact set also includes callers of its
methods, not just its direct subclasses; it does not attempt to trace
which of a subclass's *inherited* (unoverridden) methods are affected
— that's a known v1 limitation, not a straightforward graph query.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import networkx as nx


@dataclass(frozen=True)
class ImpactedSymbol:
    qualified_name: str
    kind: str
    file: str
    start_line: int
    end_line: int
    via: str  # "calls" | "inherits" | "target"


@dataclass(frozen=True)
class ImpactResult:
    symbol: str
    targets: list[ImpactedSymbol]
    affected: list[ImpactedSymbol]


def _describe(graph: nx.MultiDiGraph, node_id: str, via: str) -> ImpactedSymbol:
    data = graph.nodes[node_id]
    return ImpactedSymbol(
        qualified_name=data["qualified_name"],
        kind=data["kind"],
        file=data["file"],
        start_line=data["start_line"],
        end_line=data["end_line"],
        via=via,
    )


def _class_method_nodes(graph: nx.MultiDiGraph, class_node_id: str) -> list[str]:
    class_data = graph.nodes[class_node_id]
    prefix = f"{class_data['qualified_name']}."
    return [
        node
        for node, data in graph.nodes(data=True)
        if data.get("type") == "function"
        and data.get("file") == class_data["file"]
        and data.get("qualified_name", "").startswith(prefix)
    ]


def _resolve_targets(graph: nx.MultiDiGraph, symbol: str) -> list[str]:
    normalized = symbol.removeprefix("./")
    if normalized in graph.nodes and graph.nodes[normalized].get("type") == "module":
        return [v for _, v, data in graph.out_edges(normalized, data=True) if data.get("type") == "DEFINES"]

    matches = [
        node
        for node, data in graph.nodes(data=True)
        if data.get("type") in ("function", "class") and symbol in (data.get("qualified_name"), data.get("name"))
    ]
    targets: list[str] = []
    for node in matches:
        targets.append(node)
        if graph.nodes[node].get("type") == "class":
            targets.extend(_class_method_nodes(graph, node))
    return targets


def compute_impact(graph: nx.MultiDiGraph, symbol: str) -> ImpactResult:
    """Everything that transitively depends on `symbol`.

    `symbol` may be a function/method/class name (qualified or bare) or
    a repo-relative file path, in which case every symbol the file
    defines is treated as a target.
    """
    targets = _resolve_targets(graph, symbol)
    if not targets:
        return ImpactResult(symbol=symbol, targets=[], affected=[])

    visited = set(targets)
    queue = deque(targets)
    reason_by_id: dict[str, str] = {}

    while queue:
        node = queue.popleft()
        for u, _, data in graph.in_edges(node, data=True):
            edge_type = data.get("type")
            if edge_type not in ("CALLS", "INHERITS") or u in visited:
                continue
            visited.add(u)
            reason_by_id[u] = "calls" if edge_type == "CALLS" else "inherits"
            queue.append(u)

    affected = sorted(
        (_describe(graph, node_id, reason) for node_id, reason in reason_by_id.items()),
        key=lambda s: (s.file, s.start_line),
    )
    target_symbols = sorted(
        (_describe(graph, node_id, "target") for node_id in targets),
        key=lambda s: (s.file, s.start_line),
    )
    return ImpactResult(symbol=symbol, targets=target_symbols, affected=affected)
