from pathlib import Path

from src.indexer.graph_builder import build_graph

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _node_id(graph, file: str, qualified_name: str) -> str:
    for node, data in graph.nodes(data=True):
        if data.get("file") == file and data.get("qualified_name") == qualified_name:
            return node
    raise AssertionError(f"no node for {file}::{qualified_name}")


def _edges_of_type(graph, edge_type: str) -> set[tuple[str, str]]:
    return {(u, v) for u, v, data in graph.edges(data=True) if data.get("type") == edge_type}


def test_build_graph_node_counts():
    graph = build_graph(FIXTURES / "simple_pkg")

    modules = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    functions = [n for n, d in graph.nodes(data=True) if d.get("type") == "function"]
    classes = [n for n, d in graph.nodes(data=True) if d.get("type") == "class"]

    assert set(modules) == {"__init__.py", "main.py", "models.py", "utils.py"}
    assert len(functions) == 9  # add, multiply, run + 6 methods
    assert len(classes) == 3  # Calculator, Animal, Dog


def test_build_graph_defines_edges_cover_every_chunk():
    graph = build_graph(FIXTURES / "simple_pkg")

    add_id = _node_id(graph, "utils.py", "add")
    calculator_id = _node_id(graph, "utils.py", "Calculator")
    run_id = _node_id(graph, "main.py", "run")

    assert graph.has_edge("utils.py", add_id)
    assert graph["utils.py"][add_id][0]["type"] == "DEFINES"
    assert graph.has_edge("utils.py", calculator_id)
    assert graph.has_edge("main.py", run_id)


def test_build_graph_imports_edges():
    graph = build_graph(FIXTURES / "simple_pkg")

    imports = _edges_of_type(graph, "IMPORTS")
    assert ("main.py", "models.py") in imports
    assert ("main.py", "utils.py") in imports


def test_build_graph_inherits_edges():
    graph = build_graph(FIXTURES / "simple_pkg")

    animal_id = _node_id(graph, "models.py", "Animal")
    dog_id = _node_id(graph, "models.py", "Dog")

    assert _edges_of_type(graph, "INHERITS") == {(dog_id, animal_id)}


def test_build_graph_calls_edges_match_hand_derived_expectations():
    """Hand-derived from fixtures/simple_pkg (see its docstrings):

    - `run()` instantiates Calculator() -> Calculator.__init__
    - `run()` calls calc.add(5) -> Calculator.add (typed local var)
    - `run()` calls add(calc.value, 2) -> utils.add (bare call, imported)
    - `run()` instantiates Dog("Rex") -> Animal.__init__ (Dog has no
      own __init__, so this exercises inherited-method resolution)
    - `run()` calls dog.speak() -> Dog.speak (Dog overrides speak)
    - Calculator.add/multiply each make a bare call to the *module-level*
      add/multiply function, not to themselves, despite sharing a name
    """
    graph = build_graph(FIXTURES / "simple_pkg")

    run_id = _node_id(graph, "main.py", "run")
    calculator_init_id = _node_id(graph, "utils.py", "Calculator.__init__")
    calculator_add_id = _node_id(graph, "utils.py", "Calculator.add")
    calculator_multiply_id = _node_id(graph, "utils.py", "Calculator.multiply")
    utils_add_id = _node_id(graph, "utils.py", "add")
    utils_multiply_id = _node_id(graph, "utils.py", "multiply")
    animal_init_id = _node_id(graph, "models.py", "Animal.__init__")
    dog_speak_id = _node_id(graph, "models.py", "Dog.speak")

    assert _edges_of_type(graph, "CALLS") == {
        (run_id, calculator_init_id),
        (run_id, calculator_add_id),
        (run_id, utils_add_id),
        (run_id, animal_init_id),
        (run_id, dog_speak_id),
        (calculator_add_id, utils_add_id),
        (calculator_multiply_id, utils_multiply_id),
    }


def test_build_graph_resolves_self_recursion_and_nested_function_calls():
    graph = build_graph(FIXTURES / "edge_cases")

    cached_fib_id = _node_id(graph, "tricky.py", "cached_fib")
    outer_id = _node_id(graph, "tricky.py", "outer")
    inner_id = _node_id(graph, "tricky.py", "outer.<locals>.inner")

    calls = _edges_of_type(graph, "CALLS")
    assert (cached_fib_id, cached_fib_id) in calls
    assert (outer_id, inner_id) in calls
