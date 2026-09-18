from src.indexer.embedder import ChunkEmbedding, build_embedding_text, embed_chunks
from src.indexer.parser import CodeChunk


class FakeEmbeddingClient:
    """Records calls and returns a deterministic vector per input text."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str, str]] = []

    def embed(self, texts: list[str], model: str, input_type: str) -> list[list[float]]:
        self.calls.append((texts, model, input_type))
        return [[float(len(text))] for text in texts]


def make_chunk(chunk_id: str, name: str = "foo") -> CodeChunk:
    return CodeChunk(
        id=chunk_id,
        name=name,
        qualified_name=name,
        kind="function",
        file="mod.py",
        start_line=1,
        end_line=2,
        signature=f"def {name}():",
        docstring="does a thing.",
        source=f"def {name}():\n    pass",
    )


def test_build_embedding_text_includes_locator_and_source():
    chunk = make_chunk("mod.py::foo:1")
    text = build_embedding_text(chunk)
    assert "function foo in mod.py" in text
    assert chunk.source in text


def test_embed_chunks_returns_one_embedding_per_chunk_in_order():
    chunks = [make_chunk(f"mod.py::c{i}:{i}", name=f"c{i}") for i in range(3)]
    client = FakeEmbeddingClient()

    result = embed_chunks(chunks, client)

    assert [e.chunk_id for e in result] == [c.id for c in chunks]
    assert all(isinstance(e, ChunkEmbedding) for e in result)


def test_embed_chunks_batches_requests():
    chunks = [make_chunk(f"mod.py::c{i}:{i}", name=f"c{i}") for i in range(5)]
    client = FakeEmbeddingClient()

    embed_chunks(chunks, client, batch_size=2)

    assert len(client.calls) == 3  # batches of 2, 2, 1
    assert [len(texts) for texts, _, _ in client.calls] == [2, 2, 1]


def test_embed_chunks_passes_model_and_input_type():
    chunks = [make_chunk("mod.py::foo:1")]
    client = FakeEmbeddingClient()

    embed_chunks(chunks, client, model="voyage-code-2")

    _texts, model, input_type = client.calls[0]
    assert model == "voyage-code-2"
    assert input_type == "document"


def test_embed_chunks_empty_input_makes_no_calls():
    client = FakeEmbeddingClient()
    result = embed_chunks([], client)
    assert result == []
    assert client.calls == []
