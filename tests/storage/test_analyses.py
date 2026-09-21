from src.storage import analyses


def test_repo_key_and_repo_id():
    assert analyses.repo_key("psf", "requests") == "psf/requests"
    assert analyses.repo_id("psf", "requests", "abcdef1234567890") == "psf/requests@abcdef123456"


def test_upsert_and_get_analysis_round_trip(pg_conn):
    analyses.upsert_analysis(
        pg_conn,
        repo_key="test-psf/requests",
        commit_sha="abc123",
        status="ready",
        default_branch="main",
        file_count=10,
        chunk_count=50,
    )

    result = analyses.get_analysis(pg_conn, "test-psf/requests", "abc123")

    assert result.status == "ready"
    assert result.default_branch == "main"
    assert result.file_count == 10
    assert result.chunk_count == 50
    assert result.error_message is None


def test_get_analysis_returns_none_when_missing(pg_conn):
    assert analyses.get_analysis(pg_conn, "test-nope/nope", "abc123") is None


def test_upsert_analysis_updates_status_in_place(pg_conn):
    analyses.upsert_analysis(pg_conn, "test-owner/repo", "sha1", status="pending")
    analyses.upsert_analysis(pg_conn, "test-owner/repo", "sha1", status="ready", chunk_count=5)

    result = analyses.get_analysis(pg_conn, "test-owner/repo", "sha1")

    assert result.status == "ready"
    assert result.chunk_count == 5


def test_upsert_analysis_rejects_invalid_status(pg_conn):
    import pytest

    with pytest.raises(ValueError):
        analyses.upsert_analysis(pg_conn, "test-owner/repo", "sha1", status="bogus")


def test_get_latest_ready_analysis_ignores_non_ready_and_picks_newest(pg_conn):
    analyses.upsert_analysis(pg_conn, "test-owner/repo", "sha-old", status="ready")
    analyses.upsert_analysis(pg_conn, "test-owner/repo", "sha-failed", status="failed")
    analyses.upsert_analysis(pg_conn, "test-owner/repo", "sha-new", status="ready")

    result = analyses.get_latest_ready_analysis(pg_conn, "test-owner/repo")

    assert result.commit_sha == "sha-new"


def test_get_latest_ready_analysis_returns_none_when_only_pending(pg_conn):
    analyses.upsert_analysis(pg_conn, "test-owner/repo", "sha1", status="pending")

    assert analyses.get_latest_ready_analysis(pg_conn, "test-owner/repo") is None
