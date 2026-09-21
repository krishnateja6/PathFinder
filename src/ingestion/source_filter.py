"""Filter a downloaded repo's raw file list down to what's worth indexing,
and enforce the MVP size limits from spec section 3A.

Deliberately conservative: skip binaries, vendor/build directories, and
lockfiles, then enforce hard caps on file count and total size. Exceeding
a cap is a clean rejection (RepoTooLargeError), never a silent partial
index — an individual oversized file is excluded with a note, not
truncated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_FILE_COUNT = 500
MAX_TOTAL_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
MAX_INDIVIDUAL_FILE_SIZE_BYTES = 500 * 1024  # 500 KB

_SKIP_DIR_PARTS = {
    ".git",
    "__pycache__",
    "node_modules",
    "vendor",
    "venv",
    ".venv",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    "coverage",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "egg-info",
}

_SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "composer.lock",
    "go.sum",
}

_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".webp", ".svg",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".so", ".dylib", ".dll", ".exe", ".bin", ".o", ".a",
    ".pdf", ".mp3", ".mp4", ".mov", ".wav", ".avi",
    ".pyc", ".pyo", ".class", ".jar", ".wasm",
    ".db", ".sqlite", ".sqlite3",
}


class RepoTooLargeError(Exception):
    """Raised when a repo exceeds an MVP ingestion limit, with a clear reason."""


@dataclass(frozen=True)
class FilteredFiles:
    files: list[tuple[str, bytes]]
    skipped_oversized: list[str] = field(default_factory=list)


def _is_skipped_path(path: str) -> bool:
    parts = path.split("/")
    if any(part in _SKIP_DIR_PARTS or part.endswith(".egg-info") for part in parts[:-1]):
        return True
    filename = parts[-1]
    if filename in _SKIP_FILENAMES:
        return True
    if filename.startswith("."):
        return True
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in _BINARY_EXTENSIONS


def filter_source_files(
    raw_files: list[tuple[str, bytes]],
    max_file_count: int = MAX_FILE_COUNT,
    max_total_size_bytes: int = MAX_TOTAL_SIZE_BYTES,
    max_individual_file_size_bytes: int = MAX_INDIVIDUAL_FILE_SIZE_BYTES,
) -> FilteredFiles:
    """Skip binaries/vendor/lockfiles, then enforce the count/size caps.

    Raises RepoTooLargeError (with a human-readable reason) if the
    filtered set still exceeds `max_file_count` or `max_total_size_bytes`.
    Individual files over `max_individual_file_size_bytes` are excluded
    (recorded in `skipped_oversized`), not truncated.
    """
    candidates = [(path, content) for path, content in raw_files if not _is_skipped_path(path)]

    skipped_oversized = [path for path, content in candidates if len(content) > max_individual_file_size_bytes]
    kept = [(path, content) for path, content in candidates if len(content) <= max_individual_file_size_bytes]

    if len(kept) > max_file_count:
        raise RepoTooLargeError(
            f"repo has {len(kept)} indexable files, over the {max_file_count}-file limit for this demo"
        )

    total_size = sum(len(content) for _, content in kept)
    if total_size > max_total_size_bytes:
        raise RepoTooLargeError(
            f"repo's indexable source is {total_size / 1024 / 1024:.1f} MB, "
            f"over the {max_total_size_bytes / 1024 / 1024:.0f} MB limit for this demo"
        )

    return FilteredFiles(files=kept, skipped_oversized=skipped_oversized)
