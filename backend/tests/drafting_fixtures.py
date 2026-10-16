"""Shared helpers for Drafting Agent tests (no database or network needed)."""

import json
import uuid
from datetime import date
from pathlib import Path

from app.drafting.retrieval import RetrievedClause
from app.drafting.schemas import DealFacts

SEED_FILE = Path(__file__).resolve().parents[1] / "app" / "clauses" / "seeds" / "placeholder_clauses.json"


def seed_clauses() -> dict[str, dict]:
    return {c["clause_type"]: c for c in json.loads(SEED_FILE.read_text(encoding="utf-8"))}


def retrieved(clause_type: str, *, status: str = "staging", content: str | None = None,
              statute_refs: list[str] | None = None) -> RetrievedClause:
    s = seed_clauses()[clause_type]
    return RetrievedClause(
        clause_id=uuid.uuid4(),
        clause_type=s["clause_type"],
        contract_types=s["contract_types"],
        favoured_party=s["favoured_party"],
        statute_refs=s["statute_refs"] if statute_refs is None else statute_refs,
        version=1,
        verification_status=status,
        title=s["title"],
        content=s["content"] if content is None else content,
    )


def deal(**overrides) -> DealFacts:
    data = dict(
        contract_type="nda",
        party_a={"name": "Quenta Technologies Private Limited", "short_name": "Quenta"},
        party_b={"name": "Infosys Limited", "short_name": "Infosys"},
        effective_date=date(2026, 11, 1),
        governing_law="India",
        jurisdiction_city="Bengaluru",
        terms={"notice_period": "60 days", "payment_period": "30 days"},
    )
    data.update(overrides)
    return DealFacts(**data)


def llm_returning(*edits):
    """A fake LLM that proposes the given edits."""
    def fake(prompt, *, system):
        return {"edits": list(edits)}
    return fake
