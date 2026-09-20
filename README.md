# PathFinder (codeintel)

Agentic codebase intelligence CLI for Python repos. Answers structural questions
("what calls this," "what breaks if I change this signature") using a real
tree-sitter-derived call/import graph plus pgvector semantic search — not just
embedding similarity — grounded with `file:line` citations that are verified
before being shown.

Full design spec: [codebase-intelligence-assistant-spec.md](codebase-intelligence-assistant-spec.md).

## Why this exists

Existing AI coding tools answer "what does this code do" reasonably well via
RAG, but are weak at "what happens elsewhere if I change this" — that question
needs structural understanding (call graphs, inheritance), not semantic
similarity over text. PathFinder builds both indexes from the same parse pass
and gives an LLM agent tools to traverse the structural one, rather than
relying on a single vector search per question.

## Architecture

```
                        ┌─────────────────────┐
                        │   CLI (typer)        │
                        │  index / ask /        │
                        │  impact / graph       │
                        └──────────┬────────────┘
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        │                          │                           │
        ▼                          ▼                           ▼
┌───────────────┐        ┌──────────────────┐        ┌──────────────────┐
│   indexer/     │        │     agent/        │        │   analysis/       │
│                │        │                   │        │                   │
│ parser.py      │        │ loop.py           │        │ impact.py          │
│  tree-sitter   │        │  hand-rolled       │        │  pure graph BFS    │
│  → chunks+AST  │        │  tool-use loop     │        │  over CALLS/       │
│                │        │  vs Claude API     │        │  INHERITS edges,   │
│ graph_builder  │───────▶│                   │        │  no LLM involved   │
│  AST → CALLS/  │  reads │ tools.py           │        │                   │
│  IMPORTS/      │  graph │  the 5 agent tools │        └──────────────────┘
│  INHERITS/     │        │  semantic_search,  │
│  DEFINES edges │        │  read_file,        │
│                │        │  find_definition,  │
│ embedder.py    │        │  find_callers,     │
│  chunks →      │        │  find_callees      │
│  Voyage        │        │                   │
│  embeddings    │        │ verify.py          │
│                │        │  post-hoc citation │
│ pipeline.py    │        │  verification pass │
│  orchestrates  │        └──────────────────┘
│  all of the    │
│  above         │
└───────┬────────┘
        │
        ▼
┌───────────────────────────────┐
│           storage/              │
│                                  │
│ db.py           graph_store.py  │
│  Postgres +      pickle the      │
│  pgvector        networkx graph  │
│  semantic index  per repo_id     │
└───────────────────────────────┘
```

Two indexes are built from a single tree-sitter parse of the repo:

- **Semantic index** (`indexer/embedder.py` → `storage/db.py`): function/class
  chunks (signature + docstring + body kept together), embedded with Voyage
  and stored in pgvector.
- **Structural index** (`indexer/graph_builder.py` → `storage/graph_store.py`):
  a `networkx` graph with `Function`/`Class`/`Module` nodes and
  `CALLS`/`IMPORTS`/`INHERITS`/`DEFINES` edges, resolved statically (direct
  calls, `self`/`cls` methods with inherited-method fallback, typed local
  variables, absolute/relative imports — see the module docstring in
  `graph_builder.py` for exactly what's out of scope).

`ask` runs a hand-rolled loop over the Claude Messages API (`agent/loop.py`,
~180 lines, no agent framework) that gives the model five tools
(`agent/tools.py`) to search, read, and walk the graph across as many turns as
a question needs, then verifies every `file:line` citation in the answer
against the actual source before printing it (`agent/verify.py`). `impact` is
pure graph traversal (`analysis/impact.py`) — no LLM in the loop at all.

## Setup

```bash
uv sync --all-groups
docker compose up -d          # postgres + pgvector, for `index`/`ask`
export VOYAGE_API_KEY=...     # for `index` (embeddings)
export ANTHROPIC_API_KEY=...  # for `ask` (agent loop + citation verification)
uv run pytest
```

`graph` and `impact` only read the persisted structural graph, so they work
without either API key once a repo has been indexed.

## Usage

```bash
codeintel index <repo_path>          # build the semantic + structural index
codeintel ask "<question>"           # agentic Q&A, prints a verified answer
codeintel impact <function_or_file>  # deterministic change-impact analysis
codeintel graph <function>           # debug/demo: print callers/callees
```

`ask`, `impact`, and `graph` all operate on the repo rooted at the current
directory — `cd` into the repo you indexed before running them.

## Demo: PathFinder analyzing itself

No external repo needed to see the structural side working — run against this
repo. `index` needs a Voyage API key for embeddings, but `graph`/`impact` only
need the graph, so it's built here directly and then queried through the real
CLI:

```bash
$ python -m src.cli graph build_graph
build_graph (src/indexer/graph_builder.py:44)
  Callers (14):
    - _ctx
    - ctx
    - index_repo
    - test_build_graph_calls_edges_match_hand_derived_expectations
    - test_build_graph_defines_edges_cover_every_chunk
    - test_build_graph_imports_edges
    - test_build_graph_inherits_edges
    - test_build_graph_node_counts
    - test_build_graph_resolves_self_recursion_and_nested_function_calls
    - test_impact_of_a_class_includes_subclasses_and_method_callers
    - test_impact_of_a_file_is_everything_it_defines_treated_as_targets
    - test_impact_of_a_qualified_method_name_is_unambiguous
    - test_impact_of_add_resolves_both_ambiguous_bare_name_matches
    - test_impact_of_unknown_symbol_is_empty
  Callees (9):
    - _add_call_edges
    - _add_import_edges_and_bindings
    - _add_inherits_edges
    - _add_module_and_definition_nodes
    - _build_module_index
    - _collect_file_defs
    - iter_python_files
    - new_parser
    - parse_file_with_nodes

$ python -m src.cli impact compute_impact
Changing compute_impact (src/analysis/impact.py:80):
  7 affected call site(s):
    - impact (src/cli.py:121) [calls]
    - test_compute_impact_follows_multi_hop_caller_chains (tests/analysis/test_impact.py:15) [calls]
    - test_impact_of_add_resolves_both_ambiguous_bare_name_matches (tests/analysis/test_impact.py:31) [calls]
    - test_impact_of_a_file_is_everything_it_defines_treated_as_targets (tests/analysis/test_impact.py:44) [calls]
    - test_impact_of_a_class_includes_subclasses_and_method_callers (tests/analysis/test_impact.py:62) [calls]
    - test_impact_of_unknown_symbol_is_empty (tests/analysis/test_impact.py:74) [calls]
    - test_impact_of_a_qualified_method_name_is_unambiguous (tests/analysis/test_impact.py:83) [calls]
```

Both outputs are exactly right: `build_graph` really is called from those 14
places (the pipeline plus every test that builds a graph) and calls those 9
helpers; every real caller of `compute_impact` — the CLI's `impact` command
and all six of its own test cases — shows up as an affected call site.
`ask` (the LLM-backed command) needs live `VOYAGE_API_KEY`/`ANTHROPIC_API_KEY`
credentials to record honestly, since it makes real embedding + Claude API
calls — see [Example interaction](#example-interaction) below for the shape
of a real session against a repo with those keys configured.

### Example interaction

From the spec, showing what a multi-hop `ask` session looks like end to end
(agent internals in brackets are what actually happens — a real trace, once
credentials are configured, would show the same `find_definition` /
`find_callers` / `find_callees` tool calls this repo's own tests script):

```
> How does the retry logic work in the payment webhook handler?

[agent internally: semantic_search("payment webhook retry") →
 finds handle_payment_webhook() in webhooks/payment.py →
 read_file → sees a call to retry_with_backoff() →
 find_definition(retry_with_backoff) → reads it →
 find_callers(handle_payment_webhook) → checks if retries happen upstream too]

Answer: handle_payment_webhook (webhooks/payment.py:41) wraps the
downstream call in retry_with_backoff (utils/retry.py:12), which retries
up to 3 times with exponential backoff on any exception. There's no
upstream retry — this is the only retry layer for this path.
```

## Grounding & evaluation

Two things are checked deterministically rather than trusted because an LLM
said so:

- **Graph correctness**: every `CALLS`/`IMPORTS`/`INHERITS`/`DEFINES` edge the
  graph builder produces for `fixtures/simple_pkg` was hand-derived by reading
  that fixture's source and asserted as an exact set
  (`tests/indexer/test_graph_builder.py`), including the trickier cases —
  bare calls disambiguated from `self.` calls that share a name, and a
  constructor call resolved through an unoverridden inherited `__init__`.
- **Citation verification**: a golden set of five hand-verified claims against
  `fixtures/simple_pkg` (`tests/eval/test_citation_eval.py`) covers the
  failure modes that matter — a correct citation, a hallucinated file, an
  out-of-range line, and (the sharpest case) a citation that's real but
  attached to the *wrong* claim (`Animal.speak` misattributed with `Dog`'s
  `"Woof!"` return value). All five are classified correctly.

Semantic search (`agent/tools.py::semantic_search`) is not covered by an
offline accuracy number here: Voyage embeddings are meaningless without a
live API key (a fake embedding client, used everywhere else in the test
suite, returns the same vector for every input, so any "accuracy" measured
against it would be fabricated rather than real). Retrieval quality on real
embeddings is a natural next eval to add once the tool is run against a real
indexed repo with credentials configured.

## Known limitations

The structural index resolves the statically-common cases well and
deliberately does not chase full dynamic-call resolution — decorators,
`*args`/`**kwargs` dispatch, `getattr`-based access, calls through a module
alias (`module.func()`), and multi-base MRO (bases are walked depth-first,
first match wins, not full C3 linearization) are all left unresolved rather
than guessed at. This is a known, accepted limitation of static analysis in
general, not a bug — see the module docstrings in `indexer/graph_builder.py`
and `agent/verify.py` for the exact boundaries.

## Future work (explicitly out of v1 scope)

- PR-diff review mode
- Commit-history indexing ("why was this changed")
- Multi-language support beyond Python
- VS Code extension UI

## Testing

```bash
uv run pytest    # 77 tests; storage/agent/pipeline tests need Postgres+pgvector
uv run ruff check .
```

Storage- and agent-tool tests that need a real Postgres connection skip
gracefully if one isn't reachable (`tests/conftest.py`); CI always has one via
a service container.
