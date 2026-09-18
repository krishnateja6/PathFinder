from pathlib import Path

from src.indexer.parser import CodeChunk, parse_file, parse_repo

FIXTURES = Path(__file__).parents[2] / "fixtures"


def chunk_by_qualname(chunks: list[CodeChunk], qualified_name: str) -> CodeChunk:
    matches = [c for c in chunks if c.qualified_name == qualified_name]
    assert len(matches) == 1, f"expected exactly one chunk named {qualified_name!r}, got {matches}"
    return matches[0]


def test_parse_repo_finds_all_functions_methods_and_classes():
    chunks = parse_repo(FIXTURES / "simple_pkg")
    qualnames = {c.qualified_name for c in chunks}
    assert qualnames == {
        "add",
        "multiply",
        "Calculator",
        "Calculator.__init__",
        "Calculator.add",
        "Calculator.multiply",
        "Animal",
        "Animal.__init__",
        "Animal.speak",
        "Dog",
        "Dog.speak",
        "run",
    }


def test_function_chunk_has_signature_docstring_and_source():
    chunks = parse_repo(FIXTURES / "simple_pkg")
    add_fn = chunk_by_qualname(chunks, "add")

    assert add_fn.kind == "function"
    assert add_fn.file == "utils.py"
    assert add_fn.signature == "def add(a: int, b: int) -> int:"
    assert add_fn.docstring == "Return the sum of a and b."
    assert "return a + b" in add_fn.source
    assert add_fn.start_line == 4
    assert add_fn.end_line == 6


def test_methods_are_kind_method_and_functions_are_kind_function():
    chunks = parse_repo(FIXTURES / "simple_pkg")
    assert chunk_by_qualname(chunks, "Calculator.add").kind == "method"
    assert chunk_by_qualname(chunks, "run").kind == "function"
    assert chunk_by_qualname(chunks, "Calculator").kind == "class"


def test_method_signature_excludes_body():
    chunks = parse_repo(FIXTURES / "simple_pkg")
    method = chunk_by_qualname(chunks, "Calculator.add")
    assert method.signature == "def add(self, amount: int) -> int:"
    assert "self.value = add" not in method.signature


def test_class_signature_includes_base_classes():
    chunks = parse_repo(FIXTURES / "simple_pkg")
    dog = chunk_by_qualname(chunks, "Dog")
    assert dog.signature == "class Dog(Animal):"


def test_chunk_ids_are_unique_within_a_repo():
    chunks = parse_repo(FIXTURES / "simple_pkg")
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids))


def test_undocumented_function_has_no_docstring():
    chunks = parse_repo(FIXTURES / "edge_cases")
    fn = chunk_by_qualname(chunks, "undocumented")
    assert fn.docstring is None


def test_decorated_function_signature_includes_decorator_and_chunk_starts_there():
    chunks = parse_repo(FIXTURES / "edge_cases")
    fn = chunk_by_qualname(chunks, "cached_fib")
    assert fn.signature.startswith("@functools.lru_cache(maxsize=None)")
    assert fn.signature.endswith("def cached_fib(n: int) -> int:")
    assert fn.start_line == 12  # the decorator line, not the def line


def test_nested_function_gets_locals_qualname():
    chunks = parse_repo(FIXTURES / "edge_cases")
    qualnames = {c.qualified_name for c in chunks}
    assert "outer" in qualnames
    assert "outer.<locals>.inner" in qualnames
    inner = chunk_by_qualname(chunks, "outer.<locals>.inner")
    assert inner.kind == "function"


def test_empty_class_has_no_method_chunks():
    chunks = parse_repo(FIXTURES / "edge_cases")
    empty = chunk_by_qualname(chunks, "Empty")
    assert empty.kind == "class"
    children = [c for c in chunks if c.qualified_name.startswith("Empty.")]
    assert children == []


def test_multiline_signature_is_joined_and_normalized():
    chunks = parse_repo(FIXTURES / "edge_cases")
    fn = chunk_by_qualname(chunks, "multiline_signature")
    assert fn.signature.startswith("def multiline_signature(")
    assert fn.signature.endswith(") -> int:")
    assert fn.docstring == "Sum three numbers, using a multi-line signature."


def test_parse_file_relative_path_is_used_verbatim():
    chunks = parse_file(FIXTURES / "simple_pkg" / "utils.py", "utils.py")
    assert all(c.file == "utils.py" for c in chunks)
