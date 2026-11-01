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
    INTERNAL_BASELINE  an internal reference that RESOLVES against the real document or a schema, on a
                       layer allowed to use one. The "Internal:" prefix alone decides nothing, and a
                       well-formed reference to something that does not exist is blocked:
                         Layer 1 (completeness)  "Internal: Schema nda/indemnity"
                                 the required-clause schema entry for THIS document's type (the clause
                                 is usually missing, so there is nothing in the document to point at)
                         Layer 3 (consistency)   "Internal: Clause 3.1 vs Clause 11.2"
                                 both clauses of the pair must exist in the document's parsed clauses
                         Layer 4 (risk asymmetry) "Internal: Clause 7 baseline:liability-cap"
                                 the clause must exist in the document AND the baseline entry must exist
                                 (stub baseline entries, labelled stub)
                       Any other layer (0, 2, 5, 6) is blocked, whatever the citation says.
                       Layer 1 needs only the document's own `doc_type` (taken from the document row, never
                       from the citation string: an NDA finding citing "Schema msme/..." is blocked).
                       Layers 3 and 4 need the clause manifest of THIS version (`DocumentContext`,
                       app/schemas/clause_manifest.py). With no manifest they are blocked, never assumed
                       fine. With no document context at all, every internal citation is blocked.
                       Matching is exact everywhere: "Clause 3.1" is not "3.10", "3" is not "3.1".

Who is exempt: only lawyer-added findings (`origin == ADVOCATE`), explicitly, in `check_finding`. They
carry no layer and no agent citation. An agent-origin finding with a missing layer or citation is blocked,
never waved through, and an advocate-origin finding that carries a layer or citation is blocked as
inconsistent. `origin` is set by server code, not read from agent output.

The Wednesday corpus is `StubFixtureCorpus`: a labelled stub (statute sections only, no statute text),
not lawyer-verified. Its source refs all start with "stub:". Swap in the real corpus later by
changing `default_corpus()`; nothing else needs to move.

Parsing is strict on purpose: ASCII only, one exact shape per type, no trailing text. A citation that
is "close" is blocked, not guessed at.
"""
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping, Protocol

from fastapi import HTTPException

from app.audit import write_audit
from app.schemas.clause_manifest import ClauseManifest
from app.schemas.finding import CitationType, Finding, FindingOrigin, Layer

log = logging.getLogger("citation_gate")

GENERIC_503 = "Review is temporarily unavailable. Please try again shortly."


class BlockReason(str, Enum):
    MALFORMED = "malformed"                  # not the exact shape this citation_type allows
    NOT_IN_CORPUS = "not_in_corpus"          # well formed, but the corpus has no such source
    UNVERIFIED_CLAUSE = "unverified_clause"  # CORPUS citation names a clause that is not verified
    LAYER_NOT_ALLOWED = "layer_not_allowed"  # INTERNAL_BASELINE on a layer that may not use one
    CLAUSE_NOT_IN_DOCUMENT = "clause_not_in_document"  # internal reference to a clause the document lacks
    NOT_IN_SCHEMA = "not_in_schema"          # Layer 1 reference to a required-clause entry that does not exist
    NOT_IN_BASELINE = "not_in_baseline"      # Layer 4 reference to a baseline entry that does not exist
    NO_DOCUMENT_CONTEXT = "no_document_context"  # internal citation, but no document context was supplied
    NO_CLAUSE_MANIFEST = "no_clause_manifest"    # Layer 3/4 citation, but this version has no clause manifest


class CorpusUnavailable(Exception):
    """The corpus could not be read. The gate fails closed: the whole run aborts."""


# ---- the corpus --------------------------------------------------------------------------------

@dataclass(frozen=True)
class ClauseRecord:
    source_ref: str
    verified: bool


@dataclass(frozen=True)
class DocumentContext:
    """What the gate needs to know about the document being reviewed.

    doc_type: the document row's own doc_type (Layer 1 resolves its schema entry against this).
    clause_numbers: the clause numbers of THIS version's manifest, exactly as "Clause <n>" cites them
    ("3.1", "7", "11.2"). Matching is exact: "Clause 3" does not exist because "3.1" does.
    None means the version has no manifest: Layers 3 and 4 then block (fail closed).
    """
    doc_type: str
    clause_numbers: frozenset[str] | None = None

    @classmethod
    def from_manifest(cls, doc_type: str, manifest: ClauseManifest | None) -> "DocumentContext":
        return cls(doc_type, None if manifest is None else manifest.clause_numbers)


class Corpus(Protocol):
    is_stub: bool

    def ensure_readable(self) -> None: ...
    def find_schema_entry(self, doc_type: str, entry: str) -> str | None: ...
    def find_baseline_entry(self, entry: str) -> str | None: ...
    def find_statute(self, act: str, year: int, section: str) -> str | None: ...
    def find_case(self, citation: str) -> str | None: ...
    def find_clause(self, clause_id: str) -> ClauseRecord | None: ...


# Sections named for Wednesday: ICA s.27 and s.74, CPC s.20, MSMED Act ss.15-16. Identifiers only; no
# statute text.
STUB_STATUTES: Mapping[tuple[str, int, str], str] = {
    ("code of civil procedure", 1908, "20"): "stub:cpc-1908-s20",
    ("indian contract act", 1872, "27"): "stub:ica-1872-s27",
    ("indian contract act", 1872, "74"): "stub:ica-1872-s74",
    ("micro, small and medium enterprises development act", 2006, "15"): "stub:msmed-2006-s15",
    ("micro, small and medium enterprises development act", 2006, "16"): "stub:msmed-2006-s16",
}


# Required-clause schema (Layer 1) and risk baselines (Layer 4). Invented placeholders for the demo, NOT
# lawyer-verified. Entry ids only; no text. There is no real baseline dataset yet.
STUB_SCHEMA_ENTRIES: Mapping[str, frozenset[str]] = {
    "nda": frozenset({"definition", "confidentiality", "term", "governing_law", "dispute_resolution",
                      "indemnity", "return_of_information"}),
}
STUB_BASELINES: Mapping[str, str] = {
    "liability-cap": "stub:baseline-liability-cap",
    "indemnity-scope": "stub:baseline-indemnity-scope",
    "penalty-vs-damages": "stub:baseline-penalty-vs-damages",
}


class StubFixtureCorpus:
    """Labelled stub corpus for the demo. NOT lawyer-verified. Every source ref starts with "stub:"."""
    is_stub = True
    LABEL = "STUB corpus: demo only, not lawyer-verified"

    def __init__(self, statutes: Mapping | None = STUB_STATUTES,
                 clauses: Mapping[str, ClauseRecord] | None = None,
                 cases: Mapping[str, str] | None = None,
                 schemas: Mapping[str, frozenset[str]] | None = None,
                 baselines: Mapping[str, str] | None = None):
        self._statutes = statutes
        self._clauses = {} if clauses is None else clauses
        self._cases = {} if cases is None else cases
        self._schemas = STUB_SCHEMA_ENTRIES if schemas is None else schemas
        self._baselines = STUB_BASELINES if baselines is None else baselines

    def find_schema_entry(self, doc_type: str, entry: str) -> str | None:
        return f"stub:schema-{doc_type}-{entry}" if entry in self._schemas.get(doc_type, ()) else None

    def find_baseline_entry(self, entry: str) -> str | None:
        return self._baselines.get(entry)

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
_NUM = r"\d+(?:\.\d+)*"
_INTERNAL_PAIR = re.compile(rf"Internal: Clause (?P<a>{_NUM}) vs Clause (?P<b>{_NUM})", re.ASCII)
_INTERNAL_SCHEMA = re.compile(r"Internal: Schema (?P<doc>[a-z_]{1,40})/(?P<entry>[a-z_]{1,64})", re.ASCII)
_INTERNAL_BASELINE = re.compile(
    rf"Internal: Clause (?P<clause>{_NUM}) baseline:(?P<entry>[a-z0-9\-]{{1,64}})", re.ASCII)
_CLAUSE = re.compile(r"clause:(?P<id>[A-Za-z0-9_\-]{1,64})", re.ASCII)
_MULTI_SPACE = re.compile(r" {2,}")

# Layers that may cite an internal reference: 1 completeness, 3 cross-clause consistency, 4 risk asymmetry.
# Each has exactly one reference shape. Layers 0, 2 (statutory), 5 and 6 may not cite one at all.
INTERNAL_LAYERS = frozenset({Layer.COMPLETENESS, Layer.CONSISTENCY, Layer.RISK_ASYMMETRY})
GATE_EXEMPT_ORIGINS = frozenset({FindingOrigin.ADVOCATE})


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


def _clause_missing(num: str, document: DocumentContext) -> GateDecision | None:
    if num not in document.clause_numbers:
        return _block(BlockReason.CLAUSE_NOT_IN_DOCUMENT, f"Clause {num} is not in this document")
    return None


def _check_internal(part: str, layer: Layer | None, document: DocumentContext | None,
                    corpus: Corpus) -> GateDecision:
    if layer not in INTERNAL_LAYERS:
        name = layer.name if layer is not None else "none"
        return _block(BlockReason.LAYER_NOT_ALLOWED, f"layer {name} may not cite an internal baseline")
    shape = {Layer.COMPLETENESS: _INTERNAL_SCHEMA, Layer.CONSISTENCY: _INTERNAL_PAIR,
             Layer.RISK_ASYMMETRY: _INTERNAL_BASELINE}[layer]
    m = shape.fullmatch(part)
    if m is None:
        return _block(BlockReason.MALFORMED, f"not the internal reference shape layer {layer.name} uses: {part!r}")
    if document is None:
        return _block(BlockReason.NO_DOCUMENT_CONTEXT, "no document context was supplied to resolve against")
    if layer is Layer.COMPLETENESS:
        if not document.doc_type or m["doc"] != document.doc_type:
            return _block(BlockReason.NOT_IN_SCHEMA,
                          f"schema entry is for {m['doc']!r}, this document is {document.doc_type!r}")
        ref = corpus.find_schema_entry(document.doc_type, m["entry"])
        if ref is None:
            return _block(BlockReason.NOT_IN_SCHEMA, f"no such required-clause entry: {part!r}")
        return GateDecision(True, source_refs=(ref,))
    if document.clause_numbers is None:
        return _block(BlockReason.NO_CLAUSE_MANIFEST, "this version has no clause manifest to resolve against")
    if layer is Layer.CONSISTENCY:
        if m["a"] == m["b"]:
            return _block(BlockReason.MALFORMED, "a consistency pair needs two different clauses")
        for num in (m["a"], m["b"]):
            if (missing := _clause_missing(num, document)) is not None:
                return missing
        return GateDecision(True)
    if (missing := _clause_missing(m["clause"], document)) is not None:
        return missing
    ref = corpus.find_baseline_entry(m["entry"])
    if ref is None:
        return _block(BlockReason.NOT_IN_BASELINE, f"no such baseline entry: {part!r}")
    return GateDecision(True, source_refs=(ref,))


def check_finding(finding: Finding, corpus: Corpus, document: DocumentContext | None = None) -> GateDecision:
    """Decide one finding. A citation string may hold several parts separated by ';'; every part must resolve."""
    layer = getattr(finding, "layer", None)
    citation = getattr(finding, "citation", None)
    ctype = getattr(finding, "citation_type", None)
    # The one exemption, written out: lawyer-added findings are the advocate's own work, not agent output.
    # It keys on origin, never on a null layer or citation, so an agent finding missing either is blocked below.
    if getattr(finding, "origin", FindingOrigin.AGENT) in GATE_EXEMPT_ORIGINS:
        if layer is not None or citation is not None or ctype is not None:
            return _block(BlockReason.MALFORMED, "advocate-origin finding carries an agent layer or citation")
        return GateDecision(True)
    if not isinstance(layer, Layer):
        return _block(BlockReason.MALFORMED, "agent finding has no layer")
    text = _normalise(citation or "")
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
            d = _check_internal(part, layer, document, corpus)
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


def run_gate(findings: list[Finding], corpus: Corpus, document: DocumentContext | None = None) -> GateResult:
    """Pure decision, no I/O. Raises CorpusUnavailable if the corpus cannot be read (nothing is partial)."""
    corpus.ensure_readable()
    result = GateResult()
    for f in findings:
        try:
            d = check_finding(f, corpus, document)
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
        "finding_id": str(getattr(f, "finding_id", None)),
        "layer": getattr(getattr(f, "layer", None), "name", None),
        "rule_applied": getattr(f, "rule_applied", None), "citation": getattr(f, "citation", None),
        "citation_type": getattr(getattr(f, "citation_type", None), "value", None),
        "reason": b.reason.value, "detail": b.detail, "corpus_is_stub": corpus.is_stub,
        "payload": f.model_dump(mode="json"),
    }


def _short_hash(text) -> str | None:
    """A short SHA-256 of a citation: repeated blocks can be matched, and no contents reach the log."""
    if not text:
        return None
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def _block_log_facts(b: BlockedFinding, corpus: Corpus) -> dict:
    """What the application log may hold about a block: ids, codes and a short hash of the citation.

    The audit row keeps the payload, citation and detail. The application log never does: they can
    carry contract text (a clause quoted in a description, a citation or a detail echoing it), and
    the log is read and shipped with less care than audit_logs.
    """
    f = b.finding
    return {
        "finding_id": str(getattr(f, "finding_id", None)),
        "layer": getattr(getattr(f, "layer", None), "name", None),
        "rule_applied": getattr(f, "rule_applied", None),
        "citation_type": getattr(getattr(f, "citation_type", None), "value", None),
        "citation_sha256": _short_hash(getattr(f, "citation", None)),
        "reason": b.reason.value, "corpus_is_stub": corpus.is_stub,
    }


def log_blocks(document_id, blocked: list[BlockedFinding], corpus: Corpus,
               audit_conn: Callable | None = None) -> None:
    rows = [dict(document_id=document_id, action="citation_blocked", details=_block_details(b, corpus))
            for b in blocked]
    try:
        _write_audit_rows(rows, audit_conn)
    except Exception as e:
        # No traceback: a database error can echo the row it failed on, payload included.
        log.error("citation_blocked audit write failed (%s); document_id=%s blocks=%s",
                  type(e).__name__, document_id,
                  json.dumps([_block_log_facts(b, corpus) for b in blocked], default=str))


def log_abort(document_id, error: Exception, audit_conn: Callable | None = None) -> None:
    details = {"reason": "corpus_unreadable", "error": f"{type(error).__name__}: {error}"[:300]}
    try:
        _write_audit_rows([dict(document_id=document_id, action="citation_gate_aborted",
                                details=details)], audit_conn)
    except Exception as e:
        # The error text stays in the audit row only; the log gets its type, as for blocks.
        log.error("citation_gate_aborted audit write failed (%s); document_id=%s reason=%s error_type=%s",
                  type(e).__name__, document_id, details["reason"], type(error).__name__)


def screen_findings(findings: list[Finding], document_id, *, corpus: Corpus | None = None,
                    document: DocumentContext | None = None,
                    audit_conn: Callable | None = None) -> GateResult:
    """Gate + logging. Call before any state transition or insert; insert `result.passed` only.

    Raises HTTPException(503, generic) if the corpus is unreadable (after logging the abort).
    """
    corpus = corpus or default_corpus()
    try:
        result = run_gate(findings, corpus, document)
    except CorpusUnavailable as e:
        log_abort(document_id, e, audit_conn)
        raise HTTPException(503, GENERIC_503) from e
    if result.blocked:
        log_blocks(document_id, result.blocked, corpus, audit_conn)
    return result
