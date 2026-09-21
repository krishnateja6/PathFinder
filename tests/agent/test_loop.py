from pathlib import Path
from types import SimpleNamespace

from src.agent.loop import TOOL_SCHEMAS, AgentAnswer, run_agent
from src.agent.tools import AgentContext
from src.indexer.graph_builder import build_graph

FIXTURES = Path(__file__).parents[2] / "fixtures"


class FakeLLMClient:
    """Returns scripted responses in order, one per `create()` call."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, *, system, messages, tools):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self._responses.pop(0)


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _tool_use(*calls: tuple[str, dict, str]) -> SimpleNamespace:
    blocks = [SimpleNamespace(type="tool_use", name=name, input=inp, id=call_id) for name, inp, call_id in calls]
    return SimpleNamespace(content=blocks)


def _ctx() -> AgentContext:
    repo_root = FIXTURES / "simple_pkg"
    return AgentContext(
        repo_root=repo_root,
        repo_id="test-agent-loop",
        conn=None,
        embedding_client=None,
        graph=build_graph(repo_root),
    )


def test_run_agent_returns_immediately_when_no_tool_use():
    llm = FakeLLMClient([_text("Direct answer, no tools needed.")])

    answer = run_agent("What is this repo?", _ctx(), llm)

    assert isinstance(answer, AgentAnswer)
    assert answer.text == "Direct answer, no tools needed."
    assert answer.tool_calls == []
    assert len(llm.calls) == 1


def test_run_agent_executes_a_single_tool_call_then_answers():
    llm = FakeLLMClient(
        [
            _tool_use(("find_definition", {"symbol": "Calculator"}, "call_1")),
            _text("Calculator is defined in utils.py."),
        ]
    )

    answer = run_agent("Where is Calculator defined?", _ctx(), llm)

    assert answer.text == "Calculator is defined in utils.py."
    assert len(answer.tool_calls) == 1
    assert answer.tool_calls[0].name == "find_definition"
    assert answer.tool_calls[0].result[0]["file"] == "utils.py"


def test_run_agent_follows_a_multi_hop_call_chain():
    """Mirrors the spec's multi-hop requirement: find_definition then
    find_callees across two separate turns before answering."""
    llm = FakeLLMClient(
        [
            _tool_use(("find_definition", {"symbol": "run"}, "call_1")),
            _tool_use(("find_callees", {"function": "run"}, "call_2")),
            _text("run() calls Calculator.add, Dog.speak, and others."),
        ]
    )

    answer = run_agent("What does run() call?", _ctx(), llm)

    assert len(answer.tool_calls) == 2
    assert [tc.name for tc in answer.tool_calls] == ["find_definition", "find_callees"]
    callees = {r["qualified_name"] for r in answer.tool_calls[1].result}
    assert "Calculator.add" in callees
    assert "Dog.speak" in callees


def test_run_agent_dispatches_multiple_tool_calls_in_one_turn():
    llm = FakeLLMClient(
        [
            _tool_use(
                ("find_definition", {"symbol": "run"}, "call_1"),
                ("find_definition", {"symbol": "Calculator"}, "call_2"),
            ),
            _text("Done."),
        ]
    )

    answer = run_agent("Look up both.", _ctx(), llm)

    assert len(answer.tool_calls) == 2
    # the tool_result message sent back must have one entry per tool_use block
    tool_result_message = llm.calls[1]["messages"][-1]
    assert len(tool_result_message["content"]) == 2


def test_run_agent_reports_unknown_tool_without_crashing():
    llm = FakeLLMClient(
        [
            _tool_use(("mystery_tool", {}, "call_1")),
            _text("Recovered."),
        ]
    )

    answer = run_agent("Do something odd.", _ctx(), llm)

    assert answer.tool_calls[0].result == {"error": "unknown tool: mystery_tool"}
    assert answer.text == "Recovered."


def test_run_agent_gives_up_after_max_turns():
    llm = FakeLLMClient(
        [
            _tool_use(("find_definition", {"symbol": "run"}, "call_1")),
            _tool_use(("find_definition", {"symbol": "run"}, "call_2")),
        ]
    )

    answer = run_agent("Loop forever?", _ctx(), llm, max_turns=2)

    assert "gave up" in answer.text.lower()
    assert len(answer.tool_calls) == 2


def test_run_agent_uses_a_custom_dispatch_when_given_one():
    """A caller whose AgentContext can't support every default tool (e.g. no
    Postgres connection) can override just the tools it needs to replace."""
    llm = FakeLLMClient(
        [
            _tool_use(("semantic_search", {"query": "anything"}, "call_1")),
            _text("Done."),
        ]
    )
    custom_dispatch = {"semantic_search": lambda ctx, args: [{"qualified_name": "stubbed_result"}]}

    answer = run_agent("Search for something.", _ctx(), llm, dispatch=custom_dispatch)

    assert answer.tool_calls[0].result == [{"qualified_name": "stubbed_result"}]


def test_run_agent_default_dispatch_is_unchanged_when_no_override_given():
    llm = FakeLLMClient(
        [
            _tool_use(("find_definition", {"symbol": "Calculator"}, "call_1")),
            _text("Done."),
        ]
    )

    answer = run_agent("Where is Calculator?", _ctx(), llm)

    assert answer.tool_calls[0].result[0]["file"] == "utils.py"


def test_analyze_impact_is_registered_as_a_tool_and_reachable_via_the_loop():
    schema_names = {schema["name"] for schema in TOOL_SCHEMAS}
    assert "analyze_impact" in schema_names

    llm = FakeLLMClient(
        [
            _tool_use(("analyze_impact", {"symbol": "Animal"}, "call_1")),
            _text("Changing Animal affects run() and Dog."),
        ]
    )

    answer = run_agent("What would break if I changed Animal?", _ctx(), llm)

    affected_names = {a["qualified_name"] for a in answer.tool_calls[0].result["affected"]}
    assert affected_names == {"run", "Dog"}
