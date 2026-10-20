import json
from uuid import uuid4

from app.agents.conversational.contract import Citation, CitationSource
from app.agents.conversational.generation import Claim, GeneratedAnswer
from app.agents.conversational.ingest import ClauseChunk
from app.agents.conversational.retrieval import RetrievedChunk
from app.agents.conversational.verification import (
    LLMVerifier,
    _premise,
    verify_answer,
    _windows
)

DOC = uuid4()


def chunk(i: int, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=ClauseChunk(
            chunk_id=f"c{i}",
            document_id=DOC,
            position=i,
            clause_number=str(i),
            heading="H",
            text=text,
        ),
        score=0.6,
    )


RETRIEVED = [chunk(1, "The Term is five years."), chunk(2, "Secrecy lasts ten years after the Term.")]


def answer(*texts_and_ids) -> GeneratedAnswer:
    claims = [Claim(text=t, chunk_ids=ids) for t, ids in texts_and_ids]
    citations = [
        Citation(source=CitationSource.DOCUMENT, chunk_id="c1", snippet="x")
    ]
    return GeneratedAnswer(claims=claims, citations=citations)


class FakeVerifier:
    def __init__(self, verdicts):
        self.verdicts = verdicts

    def verify(self, claims, sources):
        return self.verdicts


class RaisingVerifier:
    def verify(self, claims, sources):
        raise RuntimeError("boom")


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        self.calls += 1
        return self.response


A2 = answer(("Five years.", ["c1"]), ("Ten years of secrecy.", ["c2"]))


def test_all_supported_passes():
    result = verify_answer(A2, RETRIEVED, FakeVerifier([True, True]))
    assert result.passed and result.unsupported == []


def test_any_unsupported_rejects_and_lists_it():
    result = verify_answer(A2, RETRIEVED, FakeVerifier([True, False]))
    assert not result.passed
    assert result.unsupported == ["Ten years of secrecy."]


def test_verifier_exception_fails_closed():
    result = verify_answer(A2, RETRIEVED, RaisingVerifier())
    assert not result.passed
    assert len(result.unsupported) == 2


def test_wrong_verdict_count_fails_closed():
    result = verify_answer(A2, RETRIEVED, FakeVerifier([True]))
    assert not result.passed


def test_premise_joins_cited_chunks_and_skips_unknown():
    claim = Claim(text="x", chunk_ids=["c1", "missing", "c2"])
    sources = {"c1": "A", "c2": "B"}
    assert _premise(claim, sources) == "A\nB"


def test_llm_verifier_parses_verdicts():
    llm = FakeLLM(json.dumps({"results": [True, False]}))
    sources = {"c1": "A", "c2": "B"}
    verdicts = LLMVerifier(llm).verify(A2.claims, sources)
    assert verdicts == [True, False]
    assert llm.calls == 1


def test_llm_verifier_non_boolean_values_are_unsupported():
    llm = FakeLLM(json.dumps({"results": ["yes", 1]}))
    assert LLMVerifier(llm).verify(A2.claims, {"c1": "A", "c2": "B"}) == [False, False]


def test_llm_verifier_bad_json_all_false():
    assert LLMVerifier(FakeLLM("nope")).verify(A2.claims, {}) == [False, False]


def test_llm_verifier_wrong_length_all_false():
    llm = FakeLLM(json.dumps({"results": [True]}))
    assert LLMVerifier(llm).verify(A2.claims, {"c1": "A", "c2": "B"}) == [False, False]

def test_windows_split_long_premise_and_skip_short():
    assert _windows("One. Two. Three.") == []
    windows = _windows("One. Two. Three. Four. Five.")
    assert windows == ["One. Two. Three.", "Two. Three. Four.", "Three. Four. Five."]