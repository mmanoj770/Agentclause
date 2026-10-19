import os

from dotenv import load_dotenv
from pydantic import BaseModel

from app.agents.conversational.retrieval import RetrievedChunk

load_dotenv()

DEFAULT_THRESHOLD = 0.30


def get_threshold() -> float:
    return float(os.environ.get("RETRIEVAL_THRESHOLD", DEFAULT_THRESHOLD))


class GateResult(BaseModel):
    passed: bool
    top_score: float | None
    threshold: float


def clamp_score(score: float) -> float:
    return max(0.0, min(1.0, score))


def retrieval_gate(
    retrieved: list[RetrievedChunk], threshold: float | None = None
) -> GateResult:
    limit = get_threshold() if threshold is None else threshold
    if not retrieved:
        return GateResult(passed=False, top_score=None, threshold=limit)
    top = clamp_score(max(r.score for r in retrieved))
    return GateResult(passed=top >= limit, top_score=top, threshold=limit)