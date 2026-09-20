from webdemo.retrieval import cosine_similarity, load_chunk_records, rank_chunks


def test_cosine_similarity_of_identical_vectors_is_one():
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0


def test_cosine_similarity_of_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_of_opposite_vectors_is_negative_one():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == -1.0


def test_cosine_similarity_handles_a_zero_vector_without_crashing():
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_rank_chunks_orders_by_similarity_and_strips_embeddings():
    query = [1.0, 0.0]
    records = [
        {"qualified_name": "far", "embedding": [0.0, 1.0]},
        {"qualified_name": "near", "embedding": [1.0, 0.0]},
        {"qualified_name": "mid", "embedding": [0.7, 0.7]},
    ]

    ranked = rank_chunks(query, records, limit=2)

    assert [r["qualified_name"] for r in ranked] == ["near", "mid"]
    assert "embedding" not in ranked[0]
    assert "embedding" not in ranked[1]


def test_rank_chunks_respects_limit():
    query = [1.0, 0.0]
    records = [{"qualified_name": str(i), "embedding": [1.0, 0.0]} for i in range(10)]

    assert len(rank_chunks(query, records, limit=3)) == 3


def test_load_chunk_records_reads_json(tmp_path):
    path = tmp_path / "chunks.json"
    path.write_text('[{"qualified_name": "foo", "embedding": [1.0]}]')

    records = load_chunk_records(path)

    assert records == [{"qualified_name": "foo", "embedding": [1.0]}]
