"""Hand-rolled tool-use loop against the Claude Messages API.

Deliberately not using an agent framework: the spec's whole point is
being able to explain exactly what the loop does, and an explicit loop
over tool_use blocks is short enough to read end to end. It searches,
reads, and follows call/import graph references across as many turns
as it needs, then returns a final grounded answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.agent.tools import (
    AgentContext,
    find_callees,
    find_callers,
    find_definition,
    read_file,
    semantic_search,
)

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 2048
MAX_TURNS = 8

SYSTEM_PROMPT = """You are a codebase intelligence assistant. Answer questions about \
the indexed repository using only the tools available to you: `semantic_search` to \
find code related to a topic when you don't know the exact symbol, `read_file` to see \
exact source, and `find_definition`/`find_callers`/`find_callees` to follow the call \
and import graph. Reason step by step: search, read, follow a call reference, check \
the caller's context, and keep going across multiple tool calls when a question needs \
it — many real questions require following 2+ call edges to answer correctly. Only \
state things you've actually seen in a tool result, and cite every claim with its \
`file:line` location. When you have enough grounded information, give a final answer \
and stop calling tools."""

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "semantic_search",
        "description": (
            "Embedding similarity search over the indexed code. Use this to find code "
            "related to a topic or behavior when you don't already know the exact symbol name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language description of the code you want."},
                "limit": {"type": "integer", "description": "Max results (default 5)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_file",
        "description": "Read exact source lines from a file in the indexed repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative file path."},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "find_definition",
        "description": "Graph lookup: find where a function, method, or class is defined.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "find_callers",
        "description": "Graph lookup: list functions/methods that call the given function or method.",
        "input_schema": {
            "type": "object",
            "properties": {"function": {"type": "string"}},
            "required": ["function"],
        },
    },
    {
        "name": "find_callees",
        "description": "Graph lookup: list functions/methods that the given function or method calls.",
        "input_schema": {
            "type": "object",
            "properties": {"function": {"type": "string"}},
            "required": ["function"],
        },
    },
]

_DISPATCH = {
    "semantic_search": lambda ctx, args: semantic_search(ctx, args["query"], limit=args.get("limit", 5)),
    "read_file": lambda ctx, args: read_file(ctx, args["path"], args.get("start_line"), args.get("end_line")),
    "find_definition": lambda ctx, args: find_definition(ctx, args["symbol"]),
    "find_callers": lambda ctx, args: find_callers(ctx, args["function"]),
    "find_callees": lambda ctx, args: find_callees(ctx, args["function"]),
}


class LLMClient(Protocol):
    def create(self, *, system: str, messages: list[dict], tools: list[dict]) -> Any: ...


class ClaudeClient:
    """Thin wrapper so the loop depends on `LLMClient`, not the SDK directly."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def create(self, *, system: str, messages: list[dict], tools: list[dict]) -> Any:
        return self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )


@dataclass
class ToolCall:
    name: str
    input: dict
    result: Any


@dataclass
class AgentAnswer:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


def run_agent(question: str, ctx: AgentContext, llm: LLMClient, max_turns: int = MAX_TURNS) -> AgentAnswer:
    """Run the tool-use loop until Claude gives a final text answer (or `max_turns` runs out)."""
    messages: list[dict] = [{"role": "user", "content": question}]
    tool_calls: list[ToolCall] = []

    for _ in range(max_turns):
        response = llm.create(system=SYSTEM_PROMPT, messages=messages, tools=TOOL_SCHEMAS)
        blocks = response.content
        messages.append({"role": "assistant", "content": blocks})

        tool_use_blocks = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
        if not tool_use_blocks:
            text = "".join(b.text for b in blocks if getattr(b, "type", None) == "text")
            return AgentAnswer(text=text, tool_calls=tool_calls)

        tool_results = []
        for block in tool_use_blocks:
            handler = _DISPATCH.get(block.name)
            if handler is None:
                result: Any = {"error": f"unknown tool: {block.name}"}
            else:
                try:
                    result = handler(ctx, block.input)
                except Exception as exc:  # noqa: BLE001 - a bad tool call shouldn't crash the whole loop
                    result = {"error": str(exc)}
            tool_calls.append(ToolCall(name=block.name, input=block.input, result=result))
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return AgentAnswer(text="Gave up after too many tool-use turns without a final answer.", tool_calls=tool_calls)
