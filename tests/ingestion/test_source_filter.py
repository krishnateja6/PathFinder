import pytest

from src.ingestion.source_filter import RepoTooLargeError, filter_source_files


def test_keeps_ordinary_source_files():
    files = [("main.py", b"print(1)"), ("src/utils.py", b"print(2)")]

    result = filter_source_files(files)

    assert {p for p, _ in result.files} == {"main.py", "src/utils.py"}
    assert result.skipped_oversized == []


def test_skips_vendor_and_build_directories():
    files = [
        ("main.py", b"code"),
        ("node_modules/pkg/index.js", b"code"),
        ("vendor/lib/thing.go", b"code"),
        ("dist/bundle.js", b"code"),
        (".git/config", b"data"),
    ]

    result = filter_source_files(files)

    assert {p for p, _ in result.files} == {"main.py"}


def test_skips_lockfiles():
    files = [("main.py", b"code"), ("package-lock.json", b"{}"), ("uv.lock", b"stuff")]

    result = filter_source_files(files)

    assert {p for p, _ in result.files} == {"main.py"}


def test_skips_binary_extensions():
    files = [("main.py", b"code"), ("logo.png", b"\x89PNG"), ("archive.zip", b"PK")]

    result = filter_source_files(files)

    assert {p for p, _ in result.files} == {"main.py"}


def test_skips_dotfiles():
    files = [("main.py", b"code"), (".env", b"SECRET=1"), (".gitignore", b"*.pyc")]

    result = filter_source_files(files)

    assert {p for p, _ in result.files} == {"main.py"}


def test_excludes_oversized_individual_file_without_dropping_the_rest():
    files = [("small.py", b"x"), ("huge.py", b"x" * 1000)]

    result = filter_source_files(files, max_individual_file_size_bytes=100)

    assert {p for p, _ in result.files} == {"small.py"}
    assert result.skipped_oversized == ["huge.py"]


def test_raises_when_file_count_exceeds_the_cap():
    files = [(f"f{i}.py", b"x") for i in range(10)]

    with pytest.raises(RepoTooLargeError, match="file"):
        filter_source_files(files, max_file_count=5)


def test_raises_when_total_size_exceeds_the_cap():
    files = [("a.py", b"x" * 1000), ("b.py", b"x" * 1000)]

    with pytest.raises(RepoTooLargeError, match="MB"):
        filter_source_files(files, max_total_size_bytes=1500)
