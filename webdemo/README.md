# Hosted demo (Vercel)

A single-page, bring-your-own-key demo of `codeintel ask`, running against
this repo's own source. This is a separate side project layered on top of
the CLI — not part of the spec's v1 scope — kept intentionally decoupled so
it can't affect the CLI's own tests, packaging, or behavior.

## How it works

- **`public/`** — a static page (no build step) with an API-key field and a
  question field.
- **`api/ask.py`** — a Vercel Python function (file-based routing, per
  [Vercel's `/api` directory convention](https://vercel.com/docs/functions/runtimes/python/api-directory)).
  It builds this repo's call/import graph fresh on cold start (fast — no API
  calls needed for that), loads precomputed chunk embeddings from
  `webdemo/data/chunk_embeddings.json`, and reuses `run_agent` /
  `verify_answer` / `annotate_answer` from `src/agent` unchanged — the only
  swapped-out piece is `semantic_search`, replaced with
  `webdemo/retrieval.py`'s brute-force cosine similarity so the demo needs no
  hosted Postgres.
- **`webdemo/build_index.py`** — a maintainer-only script that embeds every
  chunk in the repo with Voyage once. Its output is committed; the live
  function never re-runs it.

Only two API calls happen per question: Voyage embeds the question itself
(this deployment's own key), and Claude answers plus verifies citations
(the **visitor's own key**, sent once per request, never stored or logged).

## One-time setup before deploying

```bash
export VOYAGE_API_KEY=...
uv run python -m webdemo.build_index
git add webdemo/data/chunk_embeddings.json
git commit -m "chore(webdemo): regenerate chunk embeddings"
```

Re-run this whenever you want the demo's answers to reflect a source change
significant enough to matter (it's a small, cheap, one-off Voyage cost — not
something that runs per visitor request).

## Deploying

1. Import this repo into Vercel (dashboard or `vercel` CLI), with the
   **project root left as the repo root** — don't point Vercel at a
   subdirectory. `api/ask.py` and `public/` both need to be at the root for
   Vercel's zero-config static+function routing to find them, and the
   Python function needs `src/` and `webdemo/` alongside it to import from.
2. Set one environment variable in the Vercel project settings:
   `VOYAGE_API_KEY` (server-side only — this is **yours**, used only to
   embed incoming questions).
3. Do **not** set `ANTHROPIC_API_KEY` as a project env var — the whole point
   is that each visitor supplies their own, per request.
4. Deploy. Vercel auto-detects Python dependencies from the repo's
   `pyproject.toml`; no separate `requirements.txt` is needed.

## Known constraints, honestly

- **No rate limiting.** A public `/api/ask` costs you a small Voyage call
  per question and costs the visitor their own Claude usage. `MAX_TURNS` is
  capped lower (5, vs the CLI's 8) and questions are capped at 500
  characters as a cheap guardrail, but there's no per-IP throttling. Add one
  (e.g. Vercel's KV/Edge Config, or Upstash Redis) before expecting real
  public traffic.
- **Fixed demo repo.** The function always answers about *this* repo — it
  doesn't accept an arbitrary GitHub URL to index on the fly. That's a
  deliberate scope cut: indexing an arbitrary repo per visitor would need a
  hosted Postgres+pgvector instance, resource limits on cloning/parsing
  attacker-controlled repos, and per-session storage — real infrastructure
  this demo intentionally doesn't take on.
- **Embeddings go stale.** `chunk_embeddings.json` reflects whatever the
  source looked like the last time `build_index.py` ran. Semantic search
  results can reference code that's since moved; `find_definition` /
  `find_callers` / `find_callees` / `read_file` are always live and accurate
  since they query the freshly built graph and real files on every request.
