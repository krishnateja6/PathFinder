from types import SimpleNamespace

import networkx as nx
from typer.testing import CliRunner

from src import cli
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


def test_ask_command_reports_missing_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["ask", "how does this work?"])

    assert result.exit_code == 1
    assert "codeintel index" in result.output


def test_ask_command_runs_the_agent_and_prints_the_answer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_id = str(tmp_path.resolve())

    g = nx.MultiDiGraph()
    g.add_node("a.py::run:1", type="function", name="run", qualified_name="run", file="a.py", start_line=1)
    graph_store.save_graph(g, repo_id)

    class FakeLLM:
        def create(self, *, system, messages, tools):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="This repo defines run().")])

    monkeypatch.setattr(cli, "VoyageEmbeddingClient", lambda: object())
    monkeypatch.setattr(cli, "ClaudeClient", lambda: FakeLLM())
    monkeypatch.setattr(cli.db, "connect", lambda: SimpleNamespace(close=lambda: None))

    result = runner.invoke(app, ["ask", "what does this repo define?"])

    assert result.exit_code == 0
    assert "This repo defines run()." in result.output


def test_ask_command_flags_a_fabricated_citation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_id = str(tmp_path.resolve())
    (tmp_path / "a.py").write_text("def run():\n    return 1\n")

    g = nx.MultiDiGraph()
    g.add_node("a.py::run:1", type="function", name="run", qualified_name="run", file="a.py", start_line=1)
    graph_store.save_graph(g, repo_id)

    answer_text = "run() returns 1, defined at a.py:1. It also logs errors, defined at a.py:999."

    class FakeLLM:
        def __init__(self):
            self.call_count = 0

        def create(self, *, system, messages, tools):
            self.call_count += 1
            text = answer_text if self.call_count == 1 else "SUPPORTED"
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    monkeypatch.setattr(cli, "VoyageEmbeddingClient", lambda: object())
    monkeypatch.setattr(cli, "ClaudeClient", lambda: FakeLLM())
    monkeypatch.setattr(cli.db, "connect", lambda: SimpleNamespace(close=lambda: None))

    result = runner.invoke(app, ["ask", "what does run do?"])

    assert result.exit_code == 0
    assert "run() returns 1, defined at a.py:1." in result.output
    assert "a.py:999. [UNVERIFIED CITATION]" in result.output


def test_impact_command_reports_missing_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["impact", "run"])

    assert result.exit_code == 1
    assert "codeintel index" in result.output


def test_impact_command_reports_unknown_symbol(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_id = str(tmp_path.resolve())
    graph_store.save_graph(nx.MultiDiGraph(), repo_id)

    result = runner.invoke(app, ["impact", "does_not_exist"])

    assert result.exit_code == 1
    assert "No function, class, or file" in result.output


def test_impact_command_prints_affected_call_sites(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_id = str(tmp_path.resolve())

    g = nx.MultiDiGraph()
    g.add_node("a.py::run:1", type="function", kind="function", name="run", qualified_name="run", file="a.py", start_line=1, end_line=2)
    g.add_node(
        "a.py::helper:5",
        type="function",
        kind="function",
        name="helper",
        qualified_name="helper",
        file="a.py",
        start_line=5,
        end_line=6,
    )
    g.add_edge("a.py::run:1", "a.py::helper:5", type="CALLS")
    graph_store.save_graph(g, repo_id)

    result = runner.invoke(app, ["impact", "helper"])

    assert result.exit_code == 0
    assert "Changing helper (a.py:5):" in result.output
    assert "1 affected call site(s):" in result.output
    assert "run (a.py:1) [calls]" in result.output
