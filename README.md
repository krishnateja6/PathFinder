# PathFinder (codeintel)

Agentic codebase intelligence CLI for Python repos. Answers structural questions ("what calls this," "what breaks if I change this signature") using a real tree-sitter-derived call/import graph plus pgvector semantic search, not just embedding similarity — grounded with `file:line` citations that are verified before being shown.

Full design spec: [codebase-intelligence-assistant-spec.md](codebase-intelligence-assistant-spec.md).

## Status

Phase 0 (project scaffold) in progress. See the spec's Development Phases section for the full roadmap.

## Setup

```bash
uv sync --all-groups
docker compose up -d   # postgres + pgvector for local dev
uv run pytest
```

## Usage (target v1 surface)

```bash
codeintel index <repo_path>
codeintel ask "<question>"
codeintel impact <function_or_file>
codeintel graph <function>
```

## Scope

v1 is Python-only, CLI-only. PR-review mode, commit-history indexing, multi-language support, and a VS Code extension are explicitly deferred — see the spec's "Future work" section.
