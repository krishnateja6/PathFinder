from pathlib import Path

import networkx as nx

from src.analysis.impact import compute_impact
from src.indexer.graph_builder import build_graph

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _node(**attrs) -> dict:
    return {"type": "function", "kind": "function", "start_line": 1, "end_line": 1, **attrs}


def test_compute_impact_follows_multi_hop_caller_chains():
    """A calls B calls C calls target: changing target should surface all
    three as affected, not just the direct caller C."""
    graph = nx.MultiDiGraph()
    for name in ["target", "c", "b", "a"]:
        graph.add_node(name, qualified_name=name, file="m.py", **_node(name=name))
    graph.add_edge("c", "target", type="CALLS")
    graph.add_edge("b", "c", type="CALLS")
    graph.add_edge("a", "b", type="CALLS")

    result = compute_impact(graph, "target")

    assert {aff.qualified_name for aff in result.affected} == {"a", "b", "c"}
    assert all(aff.via == "calls" for aff in result.affected)


def test_impact_of_add_resolves_both_ambiguous_bare_name_matches():
    """`add` is ambiguous by design: it matches the module-level add()
    *and* Calculator.add() by simple name (same convention used by the
    `graph` CLI command and the agent's tools). Both become targets, so
    the only symbol actually affected is their shared caller, run()."""
    graph = build_graph(FIXTURES / "simple_pkg")

    result = compute_impact(graph, "add")

    assert {t.qualified_name for t in result.targets} == {"add", "Calculator.add"}
    assert {a.qualified_name for a in result.affected} == {"run"}


def test_impact_of_a_file_is_everything_it_defines_treated_as_targets():
    """Changing utils.py as a whole should only surface run() as affected:
    Calculator's own methods are targets (part of the file), not affected by it."""
    graph = build_graph(FIXTURES / "simple_pkg")

    result = compute_impact(graph, "utils.py")

    assert {t.qualified_name for t in result.targets} == {
        "add",
        "multiply",
        "Calculator",
        "Calculator.__init__",
        "Calculator.add",
        "Calculator.multiply",
    }
    assert {a.qualified_name for a in result.affected} == {"run"}


def test_impact_of_a_class_includes_subclasses_and_method_callers():
    """Animal.__init__ is called (via inheritance) by run() through Dog("Rex"),
    and Dog itself depends on Animal via INHERITS."""
    graph = build_graph(FIXTURES / "simple_pkg")

    result = compute_impact(graph, "Animal")

    assert {t.qualified_name for t in result.targets} == {"Animal", "Animal.__init__", "Animal.speak"}
    affected_by_name = {a.qualified_name: a.via for a in result.affected}
    assert affected_by_name == {"run": "calls", "Dog": "inherits"}


def test_impact_of_unknown_symbol_is_empty():
    graph = build_graph(FIXTURES / "simple_pkg")

    result = compute_impact(graph, "does_not_exist")

    assert result.targets == []
    assert result.affected == []


def test_impact_of_a_qualified_method_name_is_unambiguous():
    graph = build_graph(FIXTURES / "simple_pkg")

    result = compute_impact(graph, "Calculator.multiply")

    # only Calculator.multiply itself calls the module-level multiply(),
    # and nothing in the fixture calls calc.multiply(...)
    assert {t.qualified_name for t in result.targets} == {"Calculator.multiply"}
    assert result.affected == []
