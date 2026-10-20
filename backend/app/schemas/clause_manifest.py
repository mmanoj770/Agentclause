"""Clause manifest: which clauses a document version contains, as the Drafting Agent assembled it.

The Layer 5 citation gate resolves "Internal: Clause <n> ..." citations (Layers 3 and 4) against this
list. It is emitted by the Drafting Agent itself (each assembled clause already maps to a corpus entry),
not recovered by re-parsing text. Parsing uploaded contracts is Path 2 and stays deferred.

One manifest PER document version: a revision renumbers clauses, so a manifest never carries over.
Nothing stores a manifest yet. When it is stored it belongs with the `document_versions` row (a nullable
jsonb column, in a migration that gets its own review). Until then the stub review passes the labelled
fixture in memory, and a version with no manifest fails closed: internal citations on Layers 3 and 4 are
blocked, never assumed fine.
"""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_CLAUSE_NUMBER = re.compile(r"(0|[1-9]\d*)(\.(0|[1-9]\d*))*", re.ASCII)


class ManifestClause(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Exactly as "Clause <n>" cites it: "3", "3.1", "11.2". No leading zeros, no trailing dot.
    clause_number: str
    # The corpus entry this clause was assembled from, and the corpus version that entry was read at.
    # Both set, or both None (a clause the user typed in that has no corpus entry).
    corpus_clause_id: str | None = None
    corpus_version: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if not _CLAUSE_NUMBER.fullmatch(self.clause_number):
            raise ValueError(f"clause_number must look like '3' or '3.1', got {self.clause_number!r}")
        if (self.corpus_clause_id is None) != (self.corpus_version is None):
            raise ValueError("corpus_clause_id and corpus_version are set together or not at all")
        return self


class ClauseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version_no: int = Field(ge=1)
    produced_by: Literal["drafting_agent", "stub_fixture"]
    clauses: tuple[ManifestClause, ...]

    @model_validator(mode="after")
    def _unique_numbers(self):
        numbers = [c.clause_number for c in self.clauses]
        if len(numbers) != len(set(numbers)):
            raise ValueError("clause_number must be unique within a manifest")
        return self

    @property
    def is_stub(self) -> bool:
        return self.produced_by == "stub_fixture"

    @property
    def clause_numbers(self) -> frozenset[str]:
        return frozenset(c.clause_number for c in self.clauses)
