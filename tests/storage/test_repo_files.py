from src.storage import repo_files


def test_replace_files_and_get_file_round_trip(pg_conn):
    repo_files.replace_files(pg_conn, "test-owner/repo@abc", [("a.py", "print(1)"), ("sub/b.py", "print(2)")])

    assert repo_files.get_file(pg_conn, "test-owner/repo@abc", "a.py") == "print(1)"
    assert repo_files.get_file(pg_conn, "test-owner/repo@abc", "sub/b.py") == "print(2)"


def test_get_file_returns_none_when_missing(pg_conn):
    assert repo_files.get_file(pg_conn, "test-owner/repo@abc", "nope.py") is None


def test_list_paths_is_sorted_and_scoped_by_repo(pg_conn):
    repo_files.replace_files(pg_conn, "test-owner/repo-a@1", [("b.py", "x"), ("a.py", "y")])
    repo_files.replace_files(pg_conn, "test-owner/repo-b@1", [("z.py", "z")])

    assert repo_files.list_paths(pg_conn, "test-owner/repo-a@1") == ["a.py", "b.py"]
    assert repo_files.list_paths(pg_conn, "test-owner/repo-b@1") == ["z.py"]


def test_replace_files_is_a_full_reindex_not_additive(pg_conn):
    repo_files.replace_files(pg_conn, "test-owner/repo@abc", [("old.py", "x")])
    repo_files.replace_files(pg_conn, "test-owner/repo@abc", [("new.py", "y")])

    assert repo_files.list_paths(pg_conn, "test-owner/repo@abc") == ["new.py"]


def test_delete_repo_removes_only_that_repos_files(pg_conn):
    repo_files.replace_files(pg_conn, "test-owner/repo-a@1", [("a.py", "x")])
    repo_files.replace_files(pg_conn, "test-owner/repo-b@1", [("b.py", "y")])

    repo_files.delete_repo(pg_conn, "test-owner/repo-a@1")

    assert repo_files.list_paths(pg_conn, "test-owner/repo-a@1") == []
    assert repo_files.list_paths(pg_conn, "test-owner/repo-b@1") == ["b.py"]
