"""Small golden eval for citation verification (spec §10 Phase 4).

Each case is a hand-written claim sentence against fixtures/simple_pkg
with a known-correct expected verdict, covering the failure modes the
spec calls out: a fabricated file, an out-of-range line, a citation
that's real but points at the wrong content, and a genuinely correct
citation. The LLM verdict for cases that reach it is scripted to what
a correct judge would say — this isn't testing LLM judgment quality
(that's not unit-testable), it's testing that verify_answer's
deterministic checks and orchestration behave correctly across a
curated, hand-verified set of claims.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.verify import verify_answer

FIXTURES = Path(__file__).parents[2] / "fixtures" / "simple_pkg"


class ScriptedLLM:
    def __init__(self, verdict: str | None = None):
        self._verdict = verdict

    def create(self, *, system, messages, tools):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._verdict or "SUPPORTED")])


GOLDEN_CASES = [
    pytest.param(
        "The add function returns the sum of a and b, defined at utils.py:4-6.",
        "SUPPORTED",
        True,
        True,
        id="correct-citation-correct-claim",
    ),
    pytest.param(
        "Dog overrides speak to return 'Woof!', defined at models.py:18-20.",
        "SUPPORTED",
        True,
        True,
        id="correct-citation-correct-claim-2",
    ),
    pytest.param(
        "Calculator has a divide method, defined at utils.py:30.",
        None,
        False,
        None,
        id="hallucinated-out-of-range-line",
    ),
    pytest.param(
        "There's a rate limiter defined at ratelimit.py:1.",
        None,
        False,
        None,
        id="hallucinated-file",
    ),
    pytest.param(
        "Animal.speak returns 'Woof!', defined at models.py:10-12.",
        "UNSUPPORTED",
        True,
        False,
        id="real-citation-wrong-claim",
    ),
]


@pytest.mark.parametrize("sentence, scripted_verdict, expected_exists, expected_supported", GOLDEN_CASES)
def test_citation_eval_matches_hand_verified_expectations(
    sentence, scripted_verdict, expected_exists, expected_supported
):
    llm = ScriptedLLM(scripted_verdict)

    verified = verify_answer(sentence, FIXTURES, llm)

    assert len(verified) == 1
    assert verified[0].exists is expected_exists
    assert verified[0].supported is expected_supported
