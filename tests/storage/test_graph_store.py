import networkx as nx

from src.storage import graph_store


def _sample_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node("a.py", type="module", path="a.py")
    graph.add_node("a.py::foo:1", type="function", name="foo")
    graph.add_edge("a.py", "a.py::foo:1", type="DEFINES")
    return graph


def test_save_and_load_round_trip(tmp_path):
    graph = _sample_graph()

    saved_path = graph_store.save_graph(graph, "my-repo", store_dir=tmp_path)
    assert saved_path.exists()

    loaded = graph_store.load_graph("my-repo", store_dir=tmp_path)

    assert set(loaded.nodes) == set(graph.nodes)
    assert set(loaded.edges) == set(graph.edges)
    assert loaded.nodes["a.py::foo:1"]["name"] == "foo"


def test_has_graph_reflects_presence(tmp_path):
    assert graph_store.has_graph("my-repo", store_dir=tmp_path) is False

    graph_store.save_graph(_sample_graph(), "my-repo", store_dir=tmp_path)

    assert graph_store.has_graph("my-repo", store_dir=tmp_path) is True


def test_repo_id_with_path_separators_is_sanitized_to_a_single_file(tmp_path):
    repo_id = "/Users/dev/some/repo"

    path = graph_store.save_graph(_sample_graph(), repo_id, store_dir=tmp_path)

    assert path.parent == tmp_path
    assert path.exists()
    assert graph_store.load_graph(repo_id, store_dir=tmp_path) is not None
