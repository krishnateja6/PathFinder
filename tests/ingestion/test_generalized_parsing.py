"""Confirms parser.py/graph_builder.py need zero changes for multi-repo use.

They already take an arbitrary Path — this test proves it against a
synthetic repo built at test time in a tmp_path, not the fixtures/
directory everything else tests against.
"""

from src.indexer.graph_builder import build_graph
from src.indexer.parser import parse_repo


def test_parse_repo_and_build_graph_work_against_an_arbitrary_directory(tmp_path):
    (tmp_path / "app.py").write_text(
        "def helper():\n    return 1\n\n\ndef main():\n    return helper()\n"
    )

    chunks = parse_repo(tmp_path)
    graph = build_graph(tmp_path)

    assert {c.qualified_name for c in chunks} == {"helper", "main"}
    assert graph.number_of_nodes() == 1 + 2  # one module + two functions

    main_id = next(n for n, d in graph.nodes(data=True) if d.get("qualified_name") == "main")
    helper_id = next(n for n, d in graph.nodes(data=True) if d.get("qualified_name") == "helper")
    assert graph.has_edge(main_id, helper_id)
