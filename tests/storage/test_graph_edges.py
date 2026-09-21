import pytest

from src.storage import graph_edges


def test_replace_edges_and_get_edges_round_trip(pg_conn):
    edges = [
        ("a.py::foo:1", "a.py::bar:5", "CALLS"),
        ("a.py::Dog:10", "a.py::Animal:1", "INHERITS"),
    ]

    graph_edges.replace_edges(pg_conn, "test-owner/repo@abc", edges)

    result = set(graph_edges.get_edges(pg_conn, "test-owner/repo@abc"))
    assert result == set(edges)


def test_replace_edges_is_a_full_reindex_not_additive(pg_conn):
    graph_edges.replace_edges(pg_conn, "test-owner/repo@abc", [("a", "b", "CALLS")])
    graph_edges.replace_edges(pg_conn, "test-owner/repo@abc", [("c", "d", "IMPORTS")])

    result = graph_edges.get_edges(pg_conn, "test-owner/repo@abc")

    assert result == [("c", "d", "IMPORTS")]


def test_replace_edges_rejects_unknown_edge_type(pg_conn):
    with pytest.raises(ValueError):
        graph_edges.replace_edges(pg_conn, "test-owner/repo@abc", [("a", "b", "FROBNICATES")])


def test_get_edges_scoped_by_repo(pg_conn):
    graph_edges.replace_edges(pg_conn, "test-owner/repo-a@1", [("a", "b", "CALLS")])
    graph_edges.replace_edges(pg_conn, "test-owner/repo-b@1", [("x", "y", "CALLS")])

    assert graph_edges.get_edges(pg_conn, "test-owner/repo-a@1") == [("a", "b", "CALLS")]
    assert graph_edges.get_edges(pg_conn, "test-owner/repo-b@1") == [("x", "y", "CALLS")]


def test_delete_repo_removes_only_that_repos_edges(pg_conn):
    graph_edges.replace_edges(pg_conn, "test-owner/repo-a@1", [("a", "b", "CALLS")])
    graph_edges.replace_edges(pg_conn, "test-owner/repo-b@1", [("x", "y", "CALLS")])

    graph_edges.delete_repo(pg_conn, "test-owner/repo-a@1")

    assert graph_edges.get_edges(pg_conn, "test-owner/repo-a@1") == []
    assert graph_edges.get_edges(pg_conn, "test-owner/repo-b@1") == [("x", "y", "CALLS")]
