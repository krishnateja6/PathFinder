from pathlib import Path
from types import SimpleNamespace

from src.agent.verify import Citation, annotate_answer, extract_citations, verify_answer

FIXTURES = Path(__file__).parents[2] / "fixtures" / "simple_pkg"


class ScriptedLLM:
    """Returns one scripted SUPPORTED/UNSUPPORTED verdict per call, in order."""

    def __init__(self, verdicts: list[str]):
        self._verdicts = list(verdicts)
        self.calls: list[dict] = []

    def create(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        verdict = self._verdicts.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=verdict)])


def test_extract_citations_parses_plain_and_ranged_and_parenthesized():
    text = (
        "See add (utils.py:4-6) for the sum helper. "
        "Also utils.py:14 defines Calculator, and models.py:15 the base class."
    )

    citations = extract_citations(text)

    assert citations == [
        Citation(file="utils.py", start_line=4, end_line=6, raw="utils.py:4-6"),
        Citation(file="utils.py", start_line=14, end_line=14, raw="utils.py:14"),
        Citation(file="models.py", start_line=15, end_line=15, raw="models.py:15"),
    ]


def test_verify_answer_flags_a_nonexistent_file():
    sentence = "There's a ghost_function defined at ghost.py:1."
    llm = ScriptedLLM([])  # should never be called: file doesn't exist

    verified = verify_answer(sentence, FIXTURES, llm)

    assert len(verified) == 1
    assert verified[0].exists is False
    assert verified[0].supported is None
    assert llm.calls == []


def test_verify_answer_flags_an_out_of_range_line():
    sentence = "Something happens at utils.py:9999."
    llm = ScriptedLLM([])

    verified = verify_answer(sentence, FIXTURES, llm)

    assert verified[0].exists is False
    assert llm.calls == []


def test_verify_answer_reads_the_real_excerpt_and_respects_the_llm_verdict():
    sentence = "The add function returns the sum of a and b, defined at utils.py:4-6."
    llm = ScriptedLLM(["SUPPORTED"])

    verified = verify_answer(sentence, FIXTURES, llm)

    assert verified[0].exists is True
    assert verified[0].supported is True
    assert "def add(a: int, b: int)" in verified[0].excerpt
    # the model was shown the real excerpt, not just the claim
    assert "def add" in llm.calls[0]["messages"][0]["content"]


def test_verify_answer_marks_unsupported_when_the_model_disagrees():
    sentence = "Calculator.multiply divides two numbers, defined at utils.py:25-28."
    llm = ScriptedLLM(["UNSUPPORTED"])

    verified = verify_answer(sentence, FIXTURES, llm)

    assert verified[0].exists is True
    assert verified[0].supported is False


def test_verify_answer_handles_multiple_sentences_and_citations():
    text = (
        "The add function sums two numbers, defined at utils.py:4-6. "
        "There's also a ghost_helper at nowhere.py:1."
    )
    llm = ScriptedLLM(["SUPPORTED"])

    verified = verify_answer(text, FIXTURES, llm)

    assert len(verified) == 2
    assert verified[0].exists and verified[0].supported
    assert not verified[1].exists


def test_annotate_answer_flags_only_the_bad_sentences():
    text = "The add function sums two numbers, defined at utils.py:4-6. There's a ghost_helper at nowhere.py:1."
    llm = ScriptedLLM(["SUPPORTED"])
    verified = verify_answer(text, FIXTURES, llm)

    annotated = annotate_answer(text, verified)

    assert "The add function sums two numbers, defined at utils.py:4-6." in annotated
    assert "[UNVERIFIED CITATION]" in annotated
    assert "ghost_helper at nowhere.py:1. [UNVERIFIED CITATION]" in annotated


def test_annotate_answer_is_a_no_op_when_everything_checks_out():
    text = "The add function sums two numbers, defined at utils.py:4-6."
    llm = ScriptedLLM(["SUPPORTED"])
    verified = verify_answer(text, FIXTURES, llm)

    assert annotate_answer(text, verified) == text
