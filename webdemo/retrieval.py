"""Pure retrieval logic for the hosted web demo: brute-force cosine
similarity over a small set of precomputed chunk embeddings.

Kept separate from `src.agent.tools.semantic_search`, which requires a
live Postgres+pgvector connection the hosted demo deliberately doesn't
have (see webdemo/README.md for why). The other four agent tools
(read_file, find_definition, find_callers, find_callees) don't touch
Postgres at all and are reused unchanged from src.agent.tools.
"""

from __future__ import annotations

import json
import math
from pathlib import Path


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def load_chunk_records(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text())


def rank_chunks(query_vector: list[float], records: list[dict], limit: int = 5) -> list[dict]:
    """The `limit` records with highest cosine similarity to `query_vector`.

    Returned in the same shape as `src.agent.tools.semantic_search`'s
    results (the `embedding` field is stripped) so the agent can't tell
    the difference between this and the Postgres-backed path.
    """
    scored = sorted(records, key=lambda r: cosine_similarity(query_vector, r["embedding"]), reverse=True)
    return [{k: v for k, v in r.items() if k != "embedding"} for r in scored[:limit]]
