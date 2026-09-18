"""Turn code chunks into embeddings via Voyage AI.

The Voyage SDK sits behind a small `EmbeddingClient` protocol so the
batching/formatting logic here can be tested without a real API key or
network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.indexer.parser import CodeChunk

DEFAULT_MODEL = "voyage-code-2"
DEFAULT_BATCH_SIZE = 128


@dataclass(frozen=True)
class ChunkEmbedding:
    chunk_id: str
    vector: list[float]


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str], model: str, input_type: str) -> list[list[float]]: ...


class VoyageEmbeddingClient:
    """Thin wrapper so the rest of the codebase depends on `EmbeddingClient`, not the SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        import voyageai

        self._client = voyageai.Client(api_key=api_key)

    def embed(self, texts: list[str], model: str, input_type: str) -> list[list[float]]:
        result = self._client.embed(texts, model=model, input_type=input_type)
        return result.embeddings


def build_embedding_text(chunk: CodeChunk) -> str:
    """The text sent to the embedding model: a locator header plus the chunk's
    full source (signature, docstring, and body together, per the spec)."""
    header = f"# {chunk.kind} {chunk.qualified_name} in {chunk.file}"
    return f"{header}\n{chunk.source}"


def embed_chunks(
    chunks: list[CodeChunk],
    client: EmbeddingClient,
    model: str = DEFAULT_MODEL,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[ChunkEmbedding]:
    embeddings: list[ChunkEmbedding] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        texts = [build_embedding_text(c) for c in batch]
        vectors = client.embed(texts, model=model, input_type="document")
        embeddings.extend(ChunkEmbedding(chunk_id=c.id, vector=v) for c, v in zip(batch, vectors, strict=True))
    return embeddings
