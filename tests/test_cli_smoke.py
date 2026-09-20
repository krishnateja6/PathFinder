import networkx as nx
from typer.testing import CliRunner

from src.cli import app
from src.storage import graph_store

runner = CliRunner()


def test_cli_app_loads():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "codeintel" in result.output.lower() or "usage" in result.output.lower()


def test_graph_command_reports_missing_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["graph", "run"])

    assert result.exit_code == 1
    assert "codeintel index" in result.output


def test_graph_command_prints_callers_and_callees(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_id = str(tmp_path.resolve())

    g = nx.MultiDiGraph()
    g.add_node("a.py::run:1", type="function", name="run", qualified_name="run", file="a.py", start_line=1)
    g.add_node("a.py::helper:5", type="function", name="helper", qualified_name="helper", file="a.py", start_line=5)
    g.add_edge("a.py::run:1", "a.py::helper:5", type="CALLS")
    graph_store.save_graph(g, repo_id)

    result = runner.invoke(app, ["graph", "run"])

    assert result.exit_code == 0
    assert "run (a.py:1)" in result.output
    assert "Callees (1):" in result.output
    assert "helper" in result.output
    assert "Callers: (none)" in result.output
