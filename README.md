# PathFinder

Paste a public GitHub repository, get a grounded architecture overview, ask
it questions with citations, and run deterministic change-impact analysis —
backed by a real tree-sitter call/import graph and pgvector semantic search,
not just an LLM's guess. Also includes a separate, simpler feature: scan a
GitHub profile and get an explainable, deterministic score for each public
repo.

A CLI version of the same engine (single local repo, no web UI) still exists
under `src/cli.py` — see [Usage: CLI](#usage-cli) below. The web product is
the primary way to use this now.

## Why this exists

Existing AI coding tools answer "what does this code do" reasonably well via
RAG, but are weak at "what happens elsewhere if I change this" — that
question needs structural understanding (call graphs, inheritance), not
semantic similarity over text. PathFinder builds a real call/import graph
from the same parse pass used for embeddings, and gives an LLM agent tools to
traverse that graph directly. Claude explains structural facts; it never
invents them — every "who calls this" or "what breaks if I change this"
answer comes from a deterministic graph traversal, not a model guessing.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  web/  (React SPA, builds into public/)                              │
│  Landing → Analyze flow / Profile Scan                                │
│  Workspace: Overview | Architecture | Explorer+Chat | Impact tabs     │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ fetch("/api/...")
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  api/index.py  — one Vercel Python function, routes by self.path      │
│  (one file, deliberately — see the comment on [tool.vercel] in        │
│  pyproject.toml for why multiple files each defining `handler`         │
│  isn't safe here)                                                      │
│                                                                         │
│  POST /api/analyze        GET /api/analysis      GET /api/architecture│
│  GET  /api/files          POST /api/ask          GET /api/impact      │
│  POST /api/profile_scan   POST /api/profile_feedback                  │
└───────┬────────────────┬────────────────┬────────────────┬───────────┘
        │                │                │                │
        ▼                ▼                ▼                ▼
┌───────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ ingestion/     │ │ indexer/      │ │ agent/        │ │ profile_scan/     │
│ validator      │ │ parser        │ │ loop          │ │ (fully            │
│ github_client  │ │ graph_builder │ │ tools (6)     │ │  independent of   │
│ source_filter  │ │ embedder      │ │ verify        │ │  everything else  │
│ pipeline       │ │ generic_      │ │               │ │  on this page —   │
│ (orchestrates  │ │  chunker      │ │ analysis/     │ │  no Postgres,     │
│  the above)    │ │ tech_stack    │ │ impact        │ │  no caching)      │
└───────┬────────┘ │ pipeline (CLI)│ │ components    │ └──────────────────┘
        │          └──────┬────────┘ └──────┬────────┘
        └──────────────────┴─────────────────┘
                            │
                            ▼
                  ┌──────────────────────┐
                  │ storage/              │
                  │ db (pgvector)         │
                  │ analyses (caching)    │
                  │ graph_edges           │
                  │ repo_files            │
                  │ graph_reconstruction  │
                  │ graph_store (CLI only,│
                  │  pickle to local disk)│
                  └──────────────────────┘
```

## How analysis works

One tree-sitter parse of a repo feeds two indexes plus one derived view:

1. **Semantic index** — every function/class chunk (Python) or fixed-size
   line window (any other text file) is embedded with Voyage and stored in
   Postgres+pgvector, scoped by `repo = "owner/repo@shortsha"`.
2. **Structural index** — Python only. `indexer/graph_builder.py` builds a
   `networkx` graph with `Function`/`Class`/`Module` nodes and
   `CALLS`/`IMPORTS`/`INHERITS`/`DEFINES` edges, resolved statically (direct
   calls, `self`/`cls` methods with inherited-method fallback, typed local
   variables, absolute/relative *intra-repo* imports). Persisted as rows in
   `graph_edges` + `code_chunks` (web) or pickled to disk (CLI), and
   reconstructed into an in-memory graph on each request.
3. **Architecture diagram** — `analysis/components.py` groups files by
   top-level directory and aggregates the structural index's own `IMPORTS`
   edges up to that level. No new import-detection logic, no LLM.
4. **Agentic Q&A** — `agent/loop.py` is a hand-rolled loop (no framework,
   ~200 lines) over the Claude Messages API. It gives the model six tools
   (`agent/tools.py`): `semantic_search`, `read_file`, `find_definition`,
   `find_callers`, `find_callees`, and `analyze_impact` (a real transitive
   graph traversal, not a guess from a single `find_callers` hop). The
   system prompt explicitly tells the model that everything tools return is
   untrusted repository data, never instructions to follow.
5. **Citation verification** — `agent/verify.py` checks every `file:line`
   citation in the finished answer two ways: deterministically (does the
   file/line range exist?) and, for citations that pass, a narrow
   single-purpose LLM call asking whether the exact excerpt actually
   supports that specific sentence. Sentences that fail either check are
   flagged `[UNVERIFIED CITATION]` rather than shown as fact.

Change-impact analysis (`analysis/impact.py`) is pure graph BFS — no LLM
anywhere in that path.

## Supported languages

**Python** gets full structural analysis (call graph, impact analysis,
inheritance-aware resolution) — everything above. **Every other text file**
(JS, Go, Rust, README, config, anything that decodes as UTF-8) is still
chunked and embedded, so it's findable via semantic search and readable in
the Explorer tab — it just has no graph nodes, so `find_callers`,
`find_callees`, and Impact have nothing to say about it. The Overview tab
labels each detected language accordingly ("Full structural analysis" vs.
"Searchable, not graphed").

## Local setup

Backend:

```bash
uv sync --all-groups
docker compose up -d              # local Postgres+pgvector for dev/testing
export VOYAGE_API_KEY=...         # embeds indexed chunks and incoming questions
export GITHUB_TOKEN=...           # optional locally; raises the 60/hr GitHub limit to 5,000/hr
uv run pytest
```

Frontend (builds straight into `public/`, which Vercel serves as static
assets — see `web/vite.config.js` for why):

```bash
cd web
npm install
npm run build   # or `npm run dev` for local iteration against a running backend
```

## Environment variables

| Variable | Where it's used | Server-side secret? |
|---|---|---|
| `DATABASE_URL` | `storage/db.py` — defaults to the local docker-compose DB | N/A (connection string) |
| `VOYAGE_API_KEY` | Embeds indexed chunks and incoming questions | **Yes** — never sent to or read from the frontend |
| `GITHUB_TOKEN` | Repo ingestion + Profile Scan's GitHub API calls | **Yes** — raises rate limits; both features work unauthenticated (60/hr) without it |
| Anthropic API key | Every `ask` / Deep AI feedback call | **Never a server env var** — see below |

## Anthropic BYOK behavior

There is deliberately no `ANTHROPIC_API_KEY` server-side. Each visitor pastes
their own key in the browser (kept in that tab's `sessionStorage` only); it's
sent to `/api/ask` or `/api/profile_feedback` for that single request,
used once to construct a `ClaudeClient`, and never logged, stored, or
returned. If you're deploying this yourself: do not set `ANTHROPIC_API_KEY`
as a Vercel environment variable — the code never falls back to one, and
setting it would do nothing except sit there unused.

## Usage: CLI

The original single-repo CLI still works, operating on a local path instead
of a GitHub URL, with no web UI. It's built against
[`codebase-intelligence-assistant-spec.md`](codebase-intelligence-assistant-spec.md),
the original design spec this whole project started from:

```bash
codeintel index <repo_path>          # build the semantic + structural index
codeintel ask "<question>"           # agentic Q&A, prints a verified answer
codeintel impact <function_or_file>  # deterministic change-impact analysis
codeintel graph <function>           # debug/demo: print callers/callees
```

`ask`/`impact`/`graph` operate on the repo rooted at the current directory —
`cd` into the indexed repo first. `graph`/`impact` need no API key once a
repo's been indexed once (they only read the persisted structural graph).

## Testing

```bash
uv run pytest        # 207 tests; Postgres-dependent ones skip gracefully if unreachable
uv run ruff check .
uv run mypy src/ api/
cd web && npm run build
```

CI (`.github/workflows/ci.yml`) currently runs `pytest` and `ruff` against a
real Postgres service container on every push; it does not yet run `mypy` or
the frontend build — a good next addition, not done here to keep this phase
scoped to documentation rather than CI changes.

## Deployment (Vercel)

- **One Python function, not one per endpoint.** All 8 `/api/*` routes live
  in `api/index.py`, routed internally by `self.path`. Vercel's Python
  entrypoint resolution expects a single unambiguous handler once
  `[tool.vercel].entrypoint` is pinned in `pyproject.toml` (see that file's
  comment for the exact deployment failure this avoids) — splitting into
  multiple files each defining their own top-level `handler` reintroduces
  that ambiguity, and unlike the first time, it wouldn't be fixable the same
  way, since the config only points at one file.
- **Static frontend** ships from `public/`, built by `cd web && npm run
  build` — not something Vercel builds on deploy in this setup; run it
  locally and commit the output, same as any other build artifact checked
  into `public/`.
- **Production needs a *hosted* Postgres+pgvector** (Neon, Supabase, or
  Vercel Postgres all support pgvector) — the local `docker-compose.yml`
  instance is dev/test only and isn't reachable from Vercel.
- `/api/analyze` is a single synchronous request, not a streamed job. Hard
  size/file-count/file-size caps (`ingestion/source_filter.py`) are the
  safety valve against exceeding Vercel's function duration instead —
  `maxDuration: 60` is set in `vercel.json`.

## Security model

- `VOYAGE_API_KEY` and `GITHUB_TOKEN` are server-side secrets, read from the
  environment, never accepted from or exposed to the frontend.
- Visitor-supplied Anthropic keys are used for exactly one request each,
  never logged, stored, or shared across visitors (see BYOK section above).
- Repository content (source, README, comments, search results) is treated
  as untrusted data in the agent's system prompt — the model is explicitly
  told not to follow anything in tool results that looks like an
  instruction. This is a real, tested concern: nothing here executes
  downloaded repository code, ever — only parses and reads it.
- The frontend renders all repository-controlled content (file contents,
  chat answers) through React's default JSX interpolation, never
  `dangerouslySetInnerHTML`, so it's auto-escaped against injected
  HTML/script content.

## Known limitations

- **The architecture diagram is a directory-boundary heuristic, not
  call-graph clustering.** Components are literally "files grouped by their
  top-level directory," with edges aggregated from the same `IMPORTS` edges
  the structural graph already computes. For repos with many top-level
  directories (test suites, docs, fixtures all counted), the diagram is
  correctly reported as outside the "5–15 components" clean range rather
  than forced into an artificial grouping.
- **Chat is single-turn.** Each question starts a fresh agent loop with no
  memory of previous questions in the session — no "what about that
  function" follow-ups with implicit reference resolution.
- **`src`-layout Python packages can miss cross-boundary import edges.**
  Discovered during live verification against a real repo (`pallets/itsdangerous`):
  when code outside `src/` imports the package by its *installed* name
  (`from itsdangerous.signer import Signer`, resolved via build-system
  package remapping) rather than a path relative to the repo root, the
  import resolver — which only matches dotted paths against the repo's
  literal directory structure — doesn't follow it. Imports and calls
  *within* `src/` resolve correctly; it's specifically test-suite-to-package
  boundaries in this layout that are missed.
- **The static call/import resolver doesn't chase full dynamic dispatch** —
  decorators, `*args`/`**kwargs` dispatch, `getattr`-based access, calls
  through a module alias (`module.func()`), and multi-base MRO (bases are
  walked depth-first, first match wins, not full C3 linearization) are left
  unresolved rather than guessed at. See `indexer/graph_builder.py`'s module
  docstring for the exact boundary.
- **No per-IP rate limiting** on any endpoint yet — a public deployment
  costs you a Voyage call per ingested chunk/question and costs each visitor
  their own Claude usage, with no throttling beyond the hard per-repo size
  caps and `MAX_TURNS`/question-length caps on `/api/ask`.
- **Oversized-repo rejection is verified with synthetic data, not a real
  huge repo** — the size-checking logic is pure arithmetic over byte counts
  that doesn't care whether the bytes are real or synthetic, so a passing
  automated test was judged sufficient rather than spending the bandwidth to
  download something like the Linux kernel just to watch it get rejected.

## Explicitly deferred (out of scope for this version)

- A dedicated dependency/call-graph explorer with depth controls, separate
  from the Architecture diagram
- Execution-flow extraction ("request → middleware → service → DB")
- Architectural insights / fan-in-fan-out hotspot detection
- Multi-turn conversational memory with reference resolution
- Global search as its own feature (file/symbol/semantic search UI)
- Potentially-affected-tests detection
- Deep per-node detail panels on the architecture diagram beyond a node's
  key files
- Private repositories, GitHub OAuth, PR/diff-aware analysis
- True async/background ingestion for repos too large or slow to fit a
  single synchronous request (the `analyses.status` column already supports
  a `pending` state, so this is forward-compatible whenever it's built)
