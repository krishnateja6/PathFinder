from src.indexer.tech_stack import detect_tech_stack


def test_detects_language_histogram_by_extension():
    files = ["main.py", "utils.py", "app.js", "README.md"]

    stack = detect_tech_stack(files)

    assert stack.languages == {"Python": 2, "JavaScript": 1}


def test_detects_manifest_files_and_frameworks_hint():
    files = ["main.py", "requirements.txt", "package.json"]

    stack = detect_tech_stack(files)

    assert set(stack.manifests_detected) == {"requirements.txt", "package.json"}
    assert set(stack.frameworks_hint) == {"Python (pip)", "Node.js"}


def test_ignores_files_with_no_recognized_extension():
    stack = detect_tech_stack(["README.md", "LICENSE", "Makefile"])

    assert stack.languages == {}


def test_languages_sorted_by_count_descending():
    files = ["a.py", "b.py", "c.py", "d.js"]

    stack = detect_tech_stack(files)

    assert list(stack.languages.keys()) == ["Python", "JavaScript"]


def test_structural_languages_reports_only_python_today():
    stack = detect_tech_stack(["main.py", "app.js", "server.go"])

    assert stack.structural_languages() == {"Python"}


def test_empty_input_produces_empty_stack():
    stack = detect_tech_stack([])

    assert stack.languages == {}
    assert stack.manifests_detected == []
    assert stack.frameworks_hint == []
