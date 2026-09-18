# Codebase Intelligence Assistant — Project Specification

Working name: pick something later (Pathfinder, CodeSage, etc.). This doc is the reference spec to build against — hand it to Claude Code as context before starting implementation.

---

## 1. Problem statement

When an engineer joins a new team, or touches an unfamiliar part of a large codebase, the real cost isn't reading code — it's reconstructing the mental model of how pieces connect: what calls what, what a function assumes about its callers, what breaks if something changes. Existing AI coding tools (Copilot, Cursor, Cody) answer "what does this code do" reasonably well via RAG, but they're weak at "what happens elsewhere if I change this," because that question needs structural understanding of the codebase, not semantic similarity over text.

This project builds a tool that answers both kinds of questions, grounded in the actual repo, with citations back to exact `file:line` locations — using agentic multi-step retrieval plus a real call/import graph, not just embeddings.

## 2. Scope for v1 — read this before building anything

The full vision (multi-language, PR-review mode, VS Code extension UI) is ambitious enough to never ship if v1 tries to do all of it. **v1 is scoped hard:**

- **Single language: Python.** Don't build multi-language support until v1 works well on one.
- **CLI only.** No VS Code extension in v1 — that's a stretch goal once the core engine works.
- **Core features only:** agentic Q&A, call/import graph, change-impact analysis, citation verification.
- **Explicitly deferred to "future work":** PR-review mode, commit-history indexing, multi-language support, VS Code extension UI.

Treat the deferred list as your README's "what I'd build next" section — it's a legitimate part of the pitch, just not part of the build.

## 3. Core functionality

### 3.1 Ingestion
Point the tool at a local repo path (GitHub URL cloning can come later). It walks the repo and builds two indexes:

- **Semantic index:** parses Python files with `tree-sitter` into function/class-level chunks — signature, docstring, and body kept together, not naive line-splitting. Each chunk is embedded and stored in pgvector.
- **Structural index:** builds a call graph and import graph from the same parse — nodes are functions/classes/files, edges are "calls," "imports," "inherits." Stored as an actual graph (see §6).

### 3.2 Agentic query loop
A question like "how does auth work here" doesn't get answered by one vector search. The assistant is given tools:

- `semantic_search(query)` — embedding similarity search over the code index
- `read_file(path, line_range)` — read exact source
- `find_definition(symbol)` — graph lookup
- `find_callers(function)` — graph lookup, who calls this
- `find_callees(function)` — graph lookup, what this calls

It reasons step by step — search, read, follow a call reference, check the caller's context — until it has enough grounded information to answer. This is what allows multi-hop questions ("what happens between a login request and the token being stored") that a single retrieval pass can't answer, because the relevant pieces may not be semantically similar to each other at all — they're just connected by call chains.

### 3.3 Change-impact analysis
Given a function, class, or file, traverse the call graph to compute everything downstream that depends on it — deterministically, not an LLM guess. Output: "If you change the signature of `validate_token()`, these N call sites across these files currently assume its current behavior," with each one as a `file:line` reference.

### 3.4 Citation verification
Before showing an answer, a lightweight second pass confirms every cited `file:line` actually contains what's claimed. Claims that don't check out get dropped or flagged rather than shown as fact. This is what makes "grounded" a real property of the system instead of a claim in the README.

## 4. Example interaction

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

## 5. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python | Matches v1 scope (analyzing Python code), matches your backend background |
| Parsing | `tree-sitter` (Python grammar) | Industry-standard incremental parser, gives you a real AST to build the graph from instead of regex hacks |
| Graph storage | `networkx` in-memory for v1; consider Neo4j only if you outgrow it | networkx is enough for single-repo scale and avoids standing up a graph DB before you need one |
| Embeddings | Voyage AI (`voyage-code-2`, code-tuned) | Anthropic's recommended embeddings partner, and it's specifically trained on code rather than general prose |
| Vector store | PostgreSQL + pgvector | Same reasoning as ProfRadar — avoids a separate vector DB at this scale |
| LLM / agent loop | Anthropic Claude API, tool use, hand-rolled (no LangChain) | You want to be able to explain exactly what the agent loop is doing in an interview — a hand-rolled loop over the Messages API with tool_use blocks is ~200 lines and fully legible |
| CLI | Python `click` or `typer` | Typer gives you type-hint-based CLI definitions, less boilerplate |
| Storage/config | SQLite for local run metadata (repo indexed, last index time) | No need for a server DB for a CLI tool running locally |
| Testing | `pytest` | Standard |

No LangChain, no Celery/Redis, no web framework in v1 — this is a CLI tool operating on a local repo, and none of that infrastructure is earned yet.

## 6. Data model — the graph

Nodes:
```
Function { id, name, file, start_line, end_line, signature, docstring }
Class    { id, name, file, start_line, end_line, docstring }
Module   { id, path }
```

Edges:
```
CALLS      (Function -> Function)
IMPORTS    (Module -> Module)
INHERITS   (Class -> Class)
DEFINES    (Module -> Function | Class)
```

This is deliberately simple for v1 — resolving dynamic calls (e.g. calling a function via a variable, decorators, `getattr`) perfectly is a research problem in itself. Handle the static/common cases well (direct calls, method calls on `self`, straightforward imports) and document known limitations rather than chasing 100% resolution.

## 7. Architecture

```
CLI (typer)
   │
   ├── indexer/
   │     ├── parser.py        (tree-sitter → chunks + AST)
   │     ├── graph_builder.py (AST → networkx graph)
   │     └── embedder.py      (chunks → Voyage embeddings → pgvector)
   │
   ├── agent/
   │     ├── loop.py          (tool-use conversation loop with Claude)
   │     ├── tools.py         (semantic_search, read_file, find_definition, find_callers, find_callees)
   │     └── verify.py        (citation verification pass)
   │
   ├── analysis/
   │     └── impact.py        (graph traversal for change-impact queries)
   │
   ├── storage/
   │     ├── db.py            (pgvector connection + queries)
   │     └── graph_store.py   (networkx persistence — pickle or serialize to disk per indexed repo)
   │
   └── cli.py                 (entry point: index, ask, impact commands)
```

## 8. Project structure

```
codebase-intelligence/
│
├── src/
│   ├── indexer/
│   │   ├── parser.py
│   │   ├── graph_builder.py
│   │   └── embedder.py
│   ├── agent/
│   │   ├── loop.py
│   │   ├── tools.py
│   │   └── verify.py
│   ├── analysis/
│   │   └── impact.py
│   ├── storage/
│   │   ├── db.py
│   │   └── graph_store.py
│   └── cli.py
│
├── tests/
│   ├── indexer/
│   ├── agent/
│   ├── analysis/
│   └── eval/            # golden question → expected-citation pairs for retrieval quality
│
├── fixtures/             # small sample Python repos used for testing indexing/graph accuracy
│
├── docker-compose.yml     # just Postgres+pgvector for local dev
├── pyproject.toml
└── README.md
```

## 9. CLI commands (v1 surface)

```
codeintel index <repo_path>              # build semantic + structural index
codeintel ask "<question>"               # agentic Q&A, prints answer + citations
codeintel impact <function_or_file>      # change-impact analysis, prints affected call sites
codeintel graph <function>                # debug/demo: print callers/callees of a symbol
```

## 10. Development phases

**Phase 0 — Setup.** Repo scaffold, Docker Compose with Postgres+pgvector, pyproject/dependencies, CI skeleton (lint + test on push).

**Phase 1 — Parsing & indexing.** tree-sitter integration, chunk extraction (function/class level, signature+docstring+body), embedding generation via Voyage, storage in pgvector. Test against 2-3 small fixture repos.

**Phase 2 — Graph construction.** Build the call/import graph from the same parse pass. Validate correctness by hand against a fixture repo you know well (write down expected edges, assert the graph matches).

**Phase 3 — Agentic Q&A.** Implement the tool-use loop against the Claude API with the five tools. Start with single-hop questions, verify multi-hop reasoning works (a question that genuinely requires following 2+ call edges to answer correctly).

**Phase 4 — Citation verification.** The post-hoc check that claimed `file:line` citations are accurate. Build a small eval set of questions with known-correct citations to test this against.

**Phase 5 — Change-impact analysis.** Graph traversal from a given symbol, formatted output of affected call sites. This is pure graph algorithm work, no LLM involved — should be the most straightforward phase.

**Phase 6 — Polish & demo prep.** README with architecture diagram, a recorded demo (terminal cast or short video) showing Q&A and impact analysis on a real open-source repo, eval results written up (retrieval accuracy on your golden set).

**Future work (explicitly out of v1 scope, list in README):** PR-diff mode, commit-history indexing for "why was this changed," multi-language support, VS Code extension.

## 11. Technical risks

- **Call graph accuracy on dynamic Python.** Decorators, `*args`/`**kwargs` dispatch, dependency injection, and dynamic attribute access will produce edges you can't resolve statically. Mitigation: handle the common static cases, explicitly document what's out of scope, and don't let this become a rabbit hole — it's a known, acceptable limitation of static analysis tools in general.
- **Agent loop cost/latency.** Multi-step tool use means multiple Claude API calls per question. Cap the number of tool-call iterations per question (e.g. max 6-8 steps) so a bad reasoning loop doesn't run away in cost or time.
- **Chunking quality.** If function-level chunks are too large (a 300-line function) or too small (losing context), retrieval quality suffers. Test against real-world repos of varying style, not just clean fixtures.
- **Eval, not vibes.** Build the golden question set (§ tests/eval) early, not at the end — it's what lets you say "retrieval accuracy improved from X% to Y%" instead of "it seemed to work better."

## 12. Open questions to resolve before Phase 1

1. Which repos will you use for development/testing fixtures — your own past projects, or well-known open-source Python repos (e.g. `requests`, `flask`)? Known repos are easier to validate graph correctness against since you can read the source yourself.
2. How will you handle repos too large to fully re-embed on every `index` call — is incremental re-indexing (only changed files) in scope for v1, or is full re-index on every run acceptable for now?
3. Where do you draw the line on "common static cases" for call resolution (§11) — worth writing down explicitly so scope doesn't creep mid-build.

---

## Notes for working with Claude Code

When you start this in VS Code with the Claude Code extension: paste this whole spec in as context at the start of the session (or reference this file directly), and consider asking Claude Code to work phase by phase rather than generating the whole project at once — confirm Phase 1 works and is tested before moving to Phase 2. This keeps you able to actually explain every part of the codebase later, which matters both for debugging and for being able to talk through the project confidently in interviews.
