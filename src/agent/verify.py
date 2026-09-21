"""Post-hoc citation verification (spec §3.4).

The agent's answers cite `file:line` locations inline. This is a
second, lightweight pass over the *finished* answer — separate from
the tool-use loop — that checks each citation two ways:

1. Deterministically: does the file and line range actually exist?
   This alone catches the most damaging failure mode (a hallucinated
   citation that just looks plausible).
2. With a narrow, single-purpose LLM call: does the exact source
   excerpt at that citation actually support the specific sentence
   making the claim, rather than just existing nearby?

Sentences whose citations fail either check are flagged rather than
silently trusted, per the spec: "claims that don't check out get
dropped or flagged rather than shown as fact."
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.agent.loop import LLMClient

CITATION_RE = re.compile(r"([\w./\\-]+\.py):(\d+)(?:-(\d+))?")

VERIFY_SYSTEM_PROMPT = """You verify a single citation against its claim. You will be \
given a sentence and the exact source code it cites. Reply with exactly one word: \
SUPPORTED if the source excerpt substantiates the sentence's claim, or UNSUPPORTED if \
it doesn't (wrong content, unrelated, or the claim overstates what's actually there)."""

MAX_EXCERPT_LINES = 30


@dataclass(frozen=True)
class Citation:
    file: str
    start_line: int
    end_line: int
    raw: str


@dataclass(frozen=True)
class VerifiedClaim:
    sentence: str
    citation: Citation
    exists: bool
    supported: bool | None  # None when `exists` is False — never asked the model
    excerpt: str | None


def extract_citations(text: str) -> list[Citation]:
    citations = []
    for match in CITATION_RE.finditer(text):
        file, start, end = match.groups()
        start_line = int(start)
        end_line = int(end) if end else start_line
        citations.append(Citation(file=file, start_line=start_line, end_line=end_line, raw=match.group(0)))
    return citations


def _split_sentences(text: str) -> list[str]:
    """Not a full NLP sentence splitter — good enough for the agent's own prose."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _read_excerpt(repo_root: Path, citation: Citation) -> str | None:
    repo_root = repo_root.resolve()
    full_path = (repo_root / citation.file).resolve()
    if full_path != repo_root and repo_root not in full_path.parents:
        return None
    if not full_path.is_file():
        return None

    lines = full_path.read_text().splitlines()
    if citation.start_line < 1 or citation.start_line > len(lines):
        return None

    end = min(len(lines), citation.end_line, citation.start_line + MAX_EXCERPT_LINES - 1)
    return "\n".join(lines[citation.start_line - 1 : end])


def _ask_supported(sentence: str, citation: Citation, excerpt: str, llm: LLMClient) -> bool:
    prompt = (
        f"Sentence: {sentence}\n\n"
        f"Cited source ({citation.file}:{citation.start_line}-{citation.end_line}):\n{excerpt}"
    )
    response = llm.create(system=VERIFY_SYSTEM_PROMPT, messages=[{"role": "user", "content": prompt}], tools=[])
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    return text.strip().upper().startswith("SUPPORTED")


def verify_answer(
    answer_text: str,
    repo_root: Path,
    llm: LLMClient,
    excerpt_reader: Callable[[Citation], str | None] | None = None,
) -> list[VerifiedClaim]:
    """Check every citation in `answer_text` against the actual source it names.

    `excerpt_reader` overrides how a citation's source excerpt is fetched —
    the same override pattern as run_agent()'s `dispatch`. It exists for
    callers with no local filesystem copy of the repo to read from (a
    GitHub-ingested repo whose files live in Postgres, not on disk).
    """
    read_excerpt = excerpt_reader if excerpt_reader is not None else lambda citation: _read_excerpt(repo_root, citation)
    verified: list[VerifiedClaim] = []
    for sentence in _split_sentences(answer_text):
        for citation in extract_citations(sentence):
            excerpt = read_excerpt(citation)
            if excerpt is None:
                verified.append(VerifiedClaim(sentence, citation, exists=False, supported=None, excerpt=None))
                continue
            supported = _ask_supported(sentence, citation, excerpt, llm)
            verified.append(VerifiedClaim(sentence, citation, exists=True, supported=supported, excerpt=excerpt))
    return verified


def annotate_answer(answer_text: str, verified: list[VerifiedClaim]) -> str:
    """Flag sentences whose citations didn't check out, rather than dropping context."""
    bad_sentences = {vc.sentence for vc in verified if not vc.exists or vc.supported is False}
    if not bad_sentences:
        return answer_text

    sentences = _split_sentences(answer_text)
    annotated = [f"{s} [UNVERIFIED CITATION]" if s in bad_sentences else s for s in sentences]
    return " ".join(annotated)
