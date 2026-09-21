import networkx as nx

from src.analysis.components import ComponentEdge, derive_components


def _module_graph(files: list[str], imports: list[tuple[str, str]]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for f in files:
        graph.add_node(f, type="module", path=f)
    for source, target in imports:
        graph.add_edge(source, target, type="IMPORTS")
    return graph


def test_groups_files_by_top_level_directory():
    graph = _module_graph(
        files=["api/routes.py", "api/handlers.py", "core/engine.py", "main.py"],
        imports=[],
    )

    result = derive_components(graph, depth=1)

    ids = {c.id for c in result.components}
    assert ids == {"api", "core", "(root)"}
    api_component = next(c for c in result.components if c.id == "api")
    assert api_component.files == ["api/handlers.py", "api/routes.py"]


def test_aggregates_import_edges_between_components_with_counts():
    graph = _module_graph(
        files=["api/routes.py", "api/handlers.py", "core/engine.py"],
        imports=[("api/routes.py", "core/engine.py"), ("api/handlers.py", "core/engine.py")],
    )

    result = derive_components(graph, depth=1)

    assert result.edges == [ComponentEdge(source="api", target="core", import_count=2)]


def test_ignores_imports_within_the_same_component():
    graph = _module_graph(
        files=["core/a.py", "core/b.py"],
        imports=[("core/a.py", "core/b.py")],
    )

    result = derive_components(graph, depth=1)

    assert result.edges == []


def test_root_level_files_form_their_own_component():
    graph = _module_graph(files=["main.py", "cli.py"], imports=[])

    result = derive_components(graph, depth=1)

    assert len(result.components) == 1
    assert result.components[0].id == "(root)"
    assert result.components[0].files == ["cli.py", "main.py"]


def test_is_within_recommended_range():
    small = derive_components(_module_graph([f"d{i}/a.py" for i in range(2)], []))
    assert small.is_within_recommended_range() is False

    mid = derive_components(_module_graph([f"d{i}/a.py" for i in range(8)], []))
    assert mid.is_within_recommended_range() is True

    large = derive_components(_module_graph([f"d{i}/a.py" for i in range(30)], []))
    assert large.is_within_recommended_range() is False
