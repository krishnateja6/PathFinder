"""One-time maintainer script: precompute chunk embeddings for the hosted
web demo, so the live serverless function never has to call Voyage to
index anything — only to embed each incoming question.

This is NOT part of the deployed function. Run it locally whenever you
want the demo to reflect the current source, then commit its output.

    export VOYAGE_API_KEY=...
    uv run python -m webdemo.build_index

Commit the resulting webdemo/data/chunk_embeddings.json before deploying
to Vercel.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.indexer.embedder import VoyageEmbeddingClient, embed_chunks
from src.indexer.parser import parse_repo

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = Path(__file__).resolve().parent / "data" / "chunk_embeddings.json"


def main() -> None:
    chunks = parse_repo(REPO_ROOT)
    print(f"Parsed {len(chunks)} chunks from {REPO_ROOT}")

    client = VoyageEmbeddingClient()
    embeddings = embed_chunks(chunks, client)
    vector_by_id = {e.chunk_id: e.vector for e in embeddings}

    records = [
        {
            "qualified_name": c.qualified_name,
            "kind": c.kind,
            "file": c.file,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "signature": c.signature,
            "docstring": c.docstring,
            "embedding": vector_by_id[c.id],
        }
        for c in chunks
    ]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(records))
    print(f"Wrote {len(records)} chunk embeddings to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
