"""Deterministic tech-stack detection: a file-extension histogram plus
manifest-file presence checks. No LLM, no guessing — this is exactly the
kind of structural fact Claude should report, never invent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STRUCTURAL_EXTENSIONS = {"py"}

_LANGUAGE_BY_EXTENSION = {
    "py": "Python",
    "js": "JavaScript",
    "jsx": "JavaScript",
    "ts": "TypeScript",
    "tsx": "TypeScript",
    "go": "Go",
    "rs": "Rust",
    "java": "Java",
    "rb": "Ruby",
    "php": "PHP",
    "c": "C",
    "h": "C",
    "cpp": "C++",
    "hpp": "C++",
    "cs": "C#",
    "swift": "Swift",
    "kt": "Kotlin",
}

_MANIFEST_TO_STACK = {
    "package.json": "Node.js",
    "requirements.txt": "Python (pip)",
    "pyproject.toml": "Python (pyproject)",
    "go.mod": "Go modules",
    "Cargo.toml": "Rust (Cargo)",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java/Kotlin (Gradle)",
    "Gemfile": "Ruby (Bundler)",
    "composer.json": "PHP (Composer)",
}


@dataclass(frozen=True)
class TechStack:
    languages: dict[str, int] = field(default_factory=dict)  # language name -> file count
    manifests_detected: list[str] = field(default_factory=list)
    frameworks_hint: list[str] = field(default_factory=list)

    def structural_languages(self) -> set[str]:
        """Which detected languages get full call-graph/impact analysis today."""
        return {_LANGUAGE_BY_EXTENSION[ext] for ext in STRUCTURAL_EXTENSIONS if _LANGUAGE_BY_EXTENSION[ext] in self.languages}


def _extension_of(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return None
    return name.rsplit(".", 1)[-1].lower()


def detect_tech_stack(file_paths: list[str]) -> TechStack:
    languages: dict[str, int] = {}
    manifests: list[str] = []

    for path in file_paths:
        ext = _extension_of(path)
        if ext and ext in _LANGUAGE_BY_EXTENSION:
            language = _LANGUAGE_BY_EXTENSION[ext]
            languages[language] = languages.get(language, 0) + 1

        filename = path.rsplit("/", 1)[-1]
        if filename in _MANIFEST_TO_STACK and filename not in manifests:
            manifests.append(filename)

    frameworks_hint = [_MANIFEST_TO_STACK[m] for m in manifests]

    return TechStack(
        languages=dict(sorted(languages.items(), key=lambda kv: kv[1], reverse=True)),
        manifests_detected=manifests,
        frameworks_hint=frameworks_hint,
    )
