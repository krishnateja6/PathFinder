from src.indexer.generic_chunker import chunk_file


def test_small_file_becomes_a_single_chunk():
    content = "line1\nline2\nline3"

    chunks = chunk_file("README.md", content, window_lines=200)

    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 3
    assert chunks[0].file == "README.md"
    assert chunks[0].kind == "file_chunk"
    assert chunks[0].source == content


def test_large_file_splits_into_multiple_windows():
    content = "\n".join(f"line{i}" for i in range(1, 251))  # 250 lines

    chunks = chunk_file("big.js", content, window_lines=100)

    assert len(chunks) == 3
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 100)
    assert (chunks[1].start_line, chunks[1].end_line) == (101, 200)
    assert (chunks[2].start_line, chunks[2].end_line) == (201, 250)


def test_empty_file_produces_no_chunks():
    assert chunk_file("empty.txt", "") == []


def test_chunk_ids_and_qualified_names_are_unique_per_window():
    content = "\n".join(f"line{i}" for i in range(1, 251))

    chunks = chunk_file("big.js", content, window_lines=100)

    assert len({c.id for c in chunks}) == 3
    assert chunks[1].qualified_name == "big.js:101-200"
