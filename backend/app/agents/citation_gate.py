"""Layer 5 citation gate (R8): no agent finding is stored unless its citation resolves.

Runs at WRITE time, before a finding is inserted, for every agent-origin finding:

    screen_findings(...)  ->  GateResult(passed, blocked)

* Blocked findings are never stored and never shown. Each block is written to `audit_logs`
  (action `citation_blocked`: citation string, payload, reason).
* If the corpus cannot be read the whole run aborts: nothing is stored, no state moves, a
  `citation_gate_aborted` row is written, and the client gets a generic 503. Call `screen_findings`
  BEFORE any state transition or insert, so a retry starts from a clean slate (idempotent).
* Audit rows are written on their OWN connection and transaction. A rollback of the caller's
  transaction cannot erase them. If that write fails too, the facts go to the application log.

What each citation_type must resolve to
    STATUTORY          a statute section present in the corpus ("<Act>, <year>, s. <n>")
    CASE               a case present in the corpus
    CORPUS             a clause present in the corpus AND marked verified
    INTERNAL_BASELINE  a recognised internal reference ("Internal: Clause 3.1 vs Clause 11.2") on a
                       layer allowed to use one. The "Internal:" prefix alone decides nothing:
                       "Internal: made up" is blocked.

The Wednesday corpus is `StubFixtureCorpus`: a labelled stub (statute sections only, no statute text),
not lawyer-verified. Its source refs all start with "stub:". Swap in the real corpus later by
changing `default_corpus()`; nothing else needs to move.

Parsing is strict on purpose: ASCII only, one exact shape per type, no trailing text. A citation that
is "close" is blocked, not guessed at.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping, Protocol

from fastapi import HTTPException

from app.audit import write_audit
from app.schemas.finding import CitationType, Finding, Layer

log = logging.getLogger("citation_gate")

GENERIC_503 = "Review is temporarily unavailable. Please try again shortly."


class BlockReason(str, Enum):
    MALFORMED = "malformed"                  # not the exact shape this citation_type allows
    NOT_IN_CORPUS = "not_in_corpus"          # well formed, but the corpus has no such source
    UNVERIFIED_CLAUSE = "unverified_clause"  # CORPUS citation names a clause that is not verified
    LAYER_NOT_ALLOWED = "layer_not_allowed"  # INTERNAL_BASELINE on a layer that may not use one


class CorpusUnavailable(Exception):
    """The corpus could not be read. The gate fails closed: the whole run aborts."""


# ---- the corpus --------------------------------------------------------------------------------

@dataclass(frozen=True)
class ClauseRecord:
    source_ref: str
    verified: bool


class Corpus(Protocol):
    is_stub: bool

    def ensure_readable(self) -> None: ...
    def find_statute(self, act: str, year: int, section: str) -> str | None: ...
    def find_case(self, citation: str) -> str | None: ...
    def find_clause(self, clause_id: str) -> ClauseRecord | None: ...


# Sections named for Wednesday: ICA s.27 and s.74, MSMED Act ss.15-16. Identifiers only; no statute text.
STUB_STATUTES: Mapping[tuple[str, int, str], str] = {
    ("indian contract act", 1872, "27"): "stub:ica-1872-s27",
    ("indian contract act", 1872, "74"): "stub:ica-1872-s74",
    ("micro, small and medium enterprises development act", 2006, "15"): "stub:msmed-2006-s15",
    ("micro, small and medium enterprises development act", 2006, "16"): "stub:msmed-2006-s16",
}


class StubFixtureCorpus:
    """Labelled stub corpus for the demo. NOT lawyer-verified. Every source ref starts with "stub:"."""
    is_stub = True
    LABEL = "STUB corpus: demo only, not lawyer-verified"

    def __init__(self, statutes: Mapping | None = STUB_STATUTES,
                 clauses: Mapping[str, ClauseRecord] | None = None,
                 cases: Mapping[str, str] | None = None):
        self._statutes = statutes
        self._clauses = {} if clauses is None else clauses
        self._cases = {} if cases is None else cases

    def ensure_readable(self) -> None:
        if not isinstance(self._statutes, Mapping) or not self._statutes:
            raise CorpusUnavailable("stub corpus has no statute entries")

    def find_statute(self, act: str, year: int, section: str) -> str | None:
        return self._statutes.get((act.lower(), year, section))

    def find_case(self, citation: str) -> str | None:
        return self._cases.get(citation)

    def find_clause(self, clause_id: str) -> ClauseRecord | None:
        return self._clauses.get(clause_id)


def default_corpus() -> Corpus:
    return StubFixtureCorpus()


# ---- strict parsing ----------------------------------------------------------------------------

_STATUTE = re.compile(
    r"(?P<act>[A-Za-z][A-Za-z ,&()'\-]*?), (?P<year>\d{4}), s\. ?(?P<section>\d{1,4}[A-Z]?)", re.ASCII)
_INTERNAL = re.compile(r"Internal: Clause \d+(\.\d+)* vs Clause \d+(\.\d+)*", re.ASCII)
_CLAUSE = re.compile(r"clause:(?P<id>[A-Za-z0-9_\-]{1,64})", re.ASCII)
_MULTI_SPACE = re.compile(r" {2,}")

# Layers that may cite an internal reference: completeness, cross-clause consistency, risk asymmetry.
INTERNAL_LAYERS = frozenset({Layer.COMPLETENESS, Layer.CONSISTENCY, Layer.RISK_ASYMMETRY})


def _normalise(text: str) -> str:
    """Collapse runs of ASCII spaces and trim. Nothing else: odd Unicode stays odd and gets blocked."""
    return _MULTI_SPACE.sub(" ", text.strip(" "))


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: BlockReason | None = None
    detail: str = ""
    source_refs: tuple[str, ...] = ()


def _block(reason: BlockReason, detail: str) -> GateDecision:
    return GateDecision(False, reason, detail)


def _check_statute(part: str, corpus: Corpus) -> GateDecision:
    m = _STATUTE.fullmatch(part)
    if m is None:
        return _block(BlockReason.MALFORMED, f"not a '<Act>, <year>, s. <n>' citation: {part!r}")
    ref = corpus.find_statute(" ".join(m["act"].split()).lower(), int(m["year"]), m["section"])
    if ref is None:
        return _block(BlockReason.NOT_IN_CORPUS, f"statute section not in corpus: {part!r}")
    return GateDecision(True, source_refs=(ref,))


def _check_case(part: str, corpus: Corpus) -> GateDecision:
    ref = corpus.find_case(part)
    if ref is None:
        return _block(BlockReason.NOT_IN_CORPUS, f"case not in corpus: {part!r}")
    return GateDecision(True, source_refs=(ref,))


def _check_corpus_clause(part: str, corpus: Corpus) -> GateDecision:
    m = _CLAUSE.fullmatch(part)
    if m is None:
        return _block(BlockReason.MALFORMED, f"not a 'clause:<id>' reference: {part!r}")
    rec = corpus.find_clause(m["id"])
    if rec is None:
        return _block(BlockReason.NOT_IN_CORPUS, f"clause not in corpus: {part!r}")
    if not rec.verified:
        return _block(BlockReason.UNVERIFIED_CLAUSE, f"clause is not verified: {part!r}")
    return GateDecision(True, source_refs=(rec.source_ref,))


def _check_internal(part: str, layer: Layer | None) -> GateDecision:
    if _INTERNAL.fullmatch(part) is None:
        return _block(BlockReason.MALFORMED, f"not a recognised internal reference: {part!r}")
    if layer not in INTERNAL_LAYERS:
        name = layer.name if layer is not None else "none"
        return _block(BlockReason.LAYER_NOT_ALLOWED, f"layer {name} may not cite an internal baseline")
    return GateDecision(True)


def check_finding(finding: Finding, corpus: Corpus) -> GateDecision:
    """Decide one finding. A citation string may hold several parts separated by ';'; every part must resolve."""
    text = _normalise(finding.citation or "")
    if not text:
        return _block(BlockReason.MALFORMED, "empty citation")
    refs: list[str] = []
    for raw in text.split(";"):
        part = _normalise(raw)
        if not part:
            return _block(BlockReason.MALFORMED, "empty citation part")
        if finding.citation_type is CitationType.STATUTORY:
            d = _check_statute(part, corpus)
        elif finding.citation_type is CitationType.CASE:
            d = _check_case(part, corpus)
        elif finding.citation_type is CitationType.CORPUS:
            d = _check_corpus_clause(part, corpus)
        else:
            d = _check_internal(part, finding.layer)
        if not d.allowed:
            return d
        refs.extend(d.source_refs)
    return GateDecision(True, source_refs=tuple(refs))


# ---- the run -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class PassedFinding:
    finding: Finding
    source_refs: tuple[str, ...]


@dataclass(frozen=True)
class BlockedFinding:
    finding: Finding
    reason: BlockReason
    detail: str


@dataclass
class GateResult:
    passed: list[PassedFinding] = field(default_factory=list)
    blocked: list[BlockedFinding] = field(default_factory=list)


def run_gate(findings: list[Finding], corpus: Corpus) -> GateResult:
    """Pure decision, no I/O. Raises CorpusUnavailable if the corpus cannot be read (nothing is partial)."""
    corpus.ensure_readable()
    result = GateResult()
    for f in findings:
        try:
            d = check_finding(f, corpus)
        except CorpusUnavailable:
            raise
        except Exception as e:  # a corpus that errors mid-run is an unreadable corpus: fail closed
            raise CorpusUnavailable(f"corpus lookup failed: {type(e).__name__}") from e
        if d.allowed:
            result.passed.append(PassedFinding(f, d.source_refs))
        else:
            result.blocked.append(BlockedFinding(f, d.reason, d.detail))
    return result


# ---- logging (own connection, own transaction) -------------------------------------------------

def _pool_connection():
    from app.db import pool  # imported late: the pool exists only inside the running app
    return pool.connection()


def _write_audit_rows(rows: list[dict], audit_conn: Callable | None) -> None:
    """rows: kwargs for write_audit. Own connection + transaction; never the caller's."""
    with (audit_conn or _pool_connection)() as conn:
        with conn.transaction():
            for r in rows:
                write_audit(conn, actor_id=None, actor_role="system", **r)


def _block_details(b: BlockedFinding, corpus: Corpus) -> dict:
    f = b.finding
    return {
        "finding_id": str(f.finding_id), "layer": f.layer.name, "rule_applied": f.rule_applied,
        "citation": f.citation, "citation_type": f.citation_type.value,
        "reason": b.reason.value, "detail": b.detail, "corpus_is_stub": corpus.is_stub,
        "payload": f.model_dump(mode="json"),
    }


def log_blocks(document_id, blocked: list[BlockedFinding], corpus: Corpus,
               audit_conn: Callable | None = None) -> None:
    rows = [dict(document_id=document_id, action="citation_blocked", details=_block_details(b, corpus))
            for b in blocked]
    try:
        _write_audit_rows(rows, audit_conn)
    except Exception:
        log.exception("citation_blocked audit write failed; blocks follow: %s",
                      json.dumps([r["details"] for r in rows], default=str))


def log_abort(document_id, error: Exception, audit_conn: Callable | None = None) -> None:
    details = {"reason": "corpus_unreadable", "error": f"{type(error).__name__}: {error}"[:300]}
    try:
        _write_audit_rows([dict(document_id=document_id, action="citation_gate_aborted",
                                details=details)], audit_conn)
    except Exception:
        log.exception("citation_gate_aborted audit write failed; document_id=%s details=%s",
                      document_id, json.dumps(details))


def screen_findings(findings: list[Finding], document_id, *, corpus: Corpus | None = None,
                    audit_conn: Callable | None = None) -> GateResult:
    """Gate + logging. Call before any state transition or insert; insert `result.passed` only.

    Raises HTTPException(503, generic) if the corpus is unreadable (after logging the abort).
    """
    corpus = corpus or default_corpus()
    try:
        result = run_gate(findings, corpus)
    except CorpusUnavailable as e:
        log_abort(document_id, e, audit_conn)
        raise HTTPException(503, GENERIC_503) from e
    if result.blocked:
        log_blocks(document_id, result.blocked, corpus, audit_conn)
    return result
