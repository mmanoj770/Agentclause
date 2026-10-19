import json
from pathlib import Path
from uuid import uuid4

from app.agents.conversational.gates import clamp_score, get_threshold, retrieval_gate
from app.agents.conversational.ingest import ClauseChunk
from app.agents.conversational.retrieval import RetrievedChunk

DATA = Path(__file__).parent / "data" / "retrieval_set.json"
DOC = uuid4()


def rc(score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=ClauseChunk(
            chunk_id=f"{DOC}:0",
            document_id=DOC,
            position=0,
            clause_number="1",
            heading="Term",
            text="text",
        ),
        score=score,
    )


def test_passes_at_or_above_threshold():
    assert retrieval_gate([rc(0.5), rc(0.2)], threshold=0.4).passed
    assert retrieval_gate([rc(0.4)], threshold=0.4).passed


def test_blocks_below_threshold():
    result = retrieval_gate([rc(0.2), rc(0.1)], threshold=0.4)
    assert not result.passed
    assert result.top_score == 0.2


def test_empty_results_blocked():
    result = retrieval_gate([], threshold=0.3)
    assert not result.passed
    assert result.top_score is None


def test_uses_best_score_not_first():
    assert retrieval_gate([rc(0.1), rc(0.6)], threshold=0.5).passed


def test_clamp():
    assert clamp_score(-0.2) == 0.0
    assert clamp_score(1.4) == 1.0
    assert clamp_score(0.5) == 0.5


def test_negative_scores_blocked_and_clamped():
    result = retrieval_gate([rc(-0.3)], threshold=0.1)
    assert not result.passed
    assert result.top_score == 0.0


def test_threshold_from_env(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_THRESHOLD", "0.45")
    assert get_threshold() == 0.45
    assert not retrieval_gate([rc(0.4)]).passed
    monkeypatch.delenv("RETRIEVAL_THRESHOLD")
    assert get_threshold() == 0.30


def test_dataset_shape():
    items = json.loads(DATA.read_text(encoding="utf-8"))
    assert any(i["answerable"] for i in items)
    assert any(not i["answerable"] for i in items)
    assert all(i["clauses"] for i in items if i["answerable"])
    questions = [i["q"] for i in items]
    assert len(set(questions)) == len(questions)