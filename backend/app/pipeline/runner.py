"""R10 pipeline orchestration: run the review layers for one document version and hand it to the lawyer queue.

    POST /documents/{id}/review  ->  start_review()            drafted | revision_in_progress -> under_ai_review
                                     BackgroundTasks:
                                 ->  run_pipeline(document_id, version_id, from_state)
                                       R2 intake normalise
                                       R3 completeness + R4/R5 rules   (strict: the production default)
                                       R6 cross-clause consistency     (findings only once its config is not a placeholder)
                                       R7 risk asymmetry               (same; its score always feeds triage)
                                       R8 citation gate                (only what passes is saved)
                                       R9 triage                       (documents.triage_tier)
                                     one transaction: replace this version's agent findings, store the tier,
                                     audit, under_ai_review -> pending_lawyer_review

On failure in any layer the document goes back to the state it started from (a system-only move, added
for R10) with an `ai_review_failed` audit row naming the layer and the error type, so it never stays in
under_ai_review and the review can be started again. A run that died without reaching either outcome
(a crashed worker) is recovered when the review is started again after STALE_AFTER.

Only one run per version at a time: start_review moves the document to under_ai_review under the row
lock that transition() takes, so a second click gets a 409. Logs carry ids, layer names, counts and
timings only, never contract text.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from fastapi import HTTPException

from app.agents.citation_gate import Corpus, DocumentContext, screen_findings
from app.audit import write_audit
from app.auth.dependencies import CurrentUser
from app.documents.service import Actor, get_document, transition
from app.documents.states import DocState
from app.findings.service import insert_agent_findings
from app.pipeline import asymmetry, consistency
from app.pipeline.triage import save_triage, triage
from app.rules.api import run_review
from app.schemas.finding import Finding
from app.schemas.normalized_document import NormalizedDocument

log = logging.getLogger(__name__)

SYSTEM_ACTOR = Actor(kind="system")
REVIEWABLE = frozenset({DocState.DRAFTED, DocState.REVISION_IN_PROGRESS})
STALE_AFTER = timedelta(minutes=30)


# --- what the pipeline needs from the outside world (replaced in tests) -----------------------

def load_contract_text(conn, document_id, version_id) -> str:
    """The version's file from S3, as text. PDF and DOCX only; images have no text to review."""
    from app.agents.conversational.ingest import extract_text
    from app.config import settings
    from app.storage import s3 as storage

    row = conn.execute("select storage_key from document_versions where id = %s and document_id = %s",
                       (version_id, document_id)).fetchone()
    if row is None:
        raise ValueError("version does not belong to this document")
    if not settings.s3_bucket:
        raise RuntimeError("file storage is not configured")
    return extract_text(row["storage_key"], storage.read_object(storage._client(), row["storage_key"]))


def normalise_contract(text: str) -> NormalizedDocument:
    from app.intake.service import IntakeService
    return asyncio.run(IntakeService().normalize(text))


def our_side_from_org(conn, document_id, doc: NormalizedDocument) -> str | None:
    """The party that is the document's own organisation, if its name matches one intake found exactly
    (ignoring case and spacing). None when it doesn't: R7 then has no side to score from and is skipped."""
    row = conn.execute("select o.name from documents d join organizations o on o.id = d.org_id where d.id = %s",
                       (document_id,)).fetchone()
    if not row or not row["name"]:
        return None
    wanted = " ".join(row["name"].split()).casefold()
    return next((p for p in doc.parties if " ".join(p.split()).casefold() == wanted), None)


@dataclass
class PipelineDeps:
    load_text: Callable = load_contract_text                 # (conn, document_id, version_id) -> str
    normalise: Callable = normalise_contract                 # (text) -> NormalizedDocument
    our_side: Callable = our_side_from_org                   # (conn, document_id, doc) -> party | None
    corpus: Corpus | None = None                             # None: the gate's default corpus
    asymmetry_llm: Callable | None = None                    # R7's Gemini fallback: off until Gemini is approved


def _pool_connection():
    from app.db import pool  # imported late: the pool exists only inside the running app
    return pool.connection()


# --- starting a review (the route) ------------------------------------------------------------

def start_review(conn, user: CurrentUser, doc_id) -> dict:
    """Check the document can be reviewed and move it to under_ai_review. The caller schedules run_pipeline."""
    doc = get_document(conn, doc_id, user)  # 404 outside the caller's org
    if doc["state"] == DocState.UNDER_AI_REVIEW and recover_if_stale(conn, doc_id):
        doc = get_document(conn, doc_id, user)
    if doc["state"] not in REVIEWABLE:
        raise HTTPException(409, f"A review cannot start while the document is '{doc['state']}'")
    version = conn.execute(
        "select id, version_no from document_versions where document_id = %s "
        "order by version_no desc limit 1", (doc_id,)).fetchone()
    if version is None:
        raise HTTPException(409, "Upload the contract before requesting a review")
    if conn.execute("select 1 from findings where document_version_id = %s limit 1",
                    (version["id"],)).fetchone():
        raise HTTPException(409, "This version has already been reviewed; upload a revised version")
    from_state = DocState(doc["state"])
    transition(conn, doc_id, DocState.UNDER_AI_REVIEW, SYSTEM_ACTOR, "AI review started")
    conn.commit()  # the background run uses its own connection: it must see under_ai_review
    return {"state": DocState.UNDER_AI_REVIEW.value, "version_no": version["version_no"],
            "version_id": version["id"], "from_state": from_state.value}


def recover_if_stale(conn, doc_id) -> bool:
    """Put back a document left in under_ai_review longer than STALE_AFTER by a run that died. True if it did."""
    row = conn.execute(
        "select (now() - updated_at) > %s as stale from documents where id = %s and state = %s",
        (STALE_AFTER, doc_id, DocState.UNDER_AI_REVIEW.value)).fetchone()
    if not row or not row["stale"]:
        return False
    started = conn.execute(
        "select details->>'from' as from_state from audit_logs where document_id = %s and action = 'state_change' "
        "and details->>'to' = %s order by created_at desc limit 1",
        (doc_id, DocState.UNDER_AI_REVIEW.value)).fetchone()
    back = DocState(started["from_state"]) if started and started["from_state"] in REVIEWABLE else DocState.DRAFTED
    _fail(conn, doc_id, back, layer="unknown", error_type="StaleRun")
    conn.commit()
    return True


# --- the run (background) ---------------------------------------------------------------------

class LayerFailed(Exception):
    def __init__(self, layer: str, cause: BaseException):
        super().__init__(layer)
        self.layer, self.cause = layer, cause


def _strict(findings: list[Finding], config) -> list[Finding]:
    """Production runs strict: a layer whose config is still a placeholder adds no findings."""
    return [] if config.is_placeholder else findings


def run_layers(conn, document_id, version_id, doc_type: str, deps: PipelineDeps) -> tuple[list, dict, dict]:
    """R2 to R9. Returns (passed findings, triage result, per-layer timings and counts). Raises LayerFailed."""
    stats: dict[str, dict] = {}

    def layer(name, fn):
        started = time.monotonic()
        try:
            out = fn()
        except Exception as e:
            raise LayerFailed(name, e) from e
        stats[name] = {"ms": round((time.monotonic() - started) * 1000, 1)}
        return out

    text = layer("R2_intake_load", lambda: deps.load_text(conn, document_id, version_id))
    doc = layer("R2_intake", lambda: deps.normalise(text))
    review = layer("R3_R4_R5_rules", lambda: asyncio.run(
        run_review(doc.full_text, doc_type, strict=True, effective_date=doc.effective_date)))
    stats["R3_R4_R5_rules"].update(findings=len(review.findings), skipped=review.skipped_rules.count)

    r6 = layer("R6_consistency", lambda: consistency.run_consistency(doc))
    r6_findings = _strict(r6.findings, consistency._default_config())
    stats["R6_consistency"].update(findings=len(r6_findings), raw=len(r6.findings))

    side = layer("R7_side", lambda: deps.our_side(conn, document_id, doc))
    if side is None:
        r7_findings, score = [], 0.0
        stats["R7_asymmetry"] = {"ms": 0.0, "skipped": "no_side"}
    else:
        r7 = layer("R7_asymmetry", lambda: asymmetry.run_risk_asymmetry(doc, side, llm=deps.asymmetry_llm))
        r7_findings, score = _strict(r7.findings, asymmetry._default_config()), r7.score
        stats["R7_asymmetry"].update(findings=len(r7_findings), raw=len(r7.findings), score=score)

    findings = list(review.findings) + r6_findings + r7_findings
    gated = layer("R8_citation_gate", lambda: screen_findings(findings, document_id, corpus=deps.corpus,
                                                              document=DocumentContext(doc_type)))
    stats["R8_citation_gate"].update(passed=len(gated.passed), blocked=len(gated.blocked))
    tier = layer("R9_triage", lambda: triage([p.finding for p in gated.passed], asymmetry_score=score))
    stats["R9_triage"].update(tier=tier["review_tier"])
    return gated.passed, tier, stats


def save_results(conn, document_id, version_id, passed, tier: dict, stats: dict) -> int:
    """One transaction: replace this version's agent findings (never lawyer-added ones), store the tier,
    audit, and hand the document to the lawyer queue."""
    with conn.transaction():
        conn.execute("delete from findings where document_version_id = %s and coalesce(advocate_action, '') <> 'add'",
                     (version_id,))
        created = insert_agent_findings(conn, document_id, version_id, passed)
        save_triage(conn, document_id, tier)
        write_audit(conn, document_id=document_id, actor_id=None, actor_role="system", action="findings_created",
                    details={"count": created, "version_id": str(version_id), "strict": True, "layers": stats})
        transition(conn, document_id, DocState.PENDING_LAWYER_REVIEW, SYSTEM_ACTOR, "AI review finished")
    return created


def _fail(conn, document_id, back_to: DocState, *, layer: str, error_type: str) -> None:
    with conn.transaction():
        write_audit(conn, document_id=document_id, actor_id=None, actor_role="system", action="ai_review_failed",
                    details={"layer": layer, "error_type": error_type, "returned_to": back_to.value})
        transition(conn, document_id, back_to, SYSTEM_ACTOR, f"AI review failed in {layer}")


def run_pipeline(document_id, version_id, from_state: str, *, deps: PipelineDeps | None = None,
                 connection: Callable | None = None) -> dict:
    """The background task. Never raises: every outcome ends in pending_lawyer_review or back in from_state."""
    deps = deps or PipelineDeps()
    started = time.monotonic()
    back_to = DocState(from_state) if from_state in REVIEWABLE else DocState.DRAFTED
    with (connection or _pool_connection)() as conn:
        layer = "setup"
        try:
            row = conn.execute("select doc_type, state from documents where id = %s", (document_id,)).fetchone()
            if row is None or row["state"] != DocState.UNDER_AI_REVIEW:
                log.warning("pipeline: document_id=%s is not under_ai_review; nothing to do", document_id)
                return {"outcome": "skipped"}
            passed, tier, stats = run_layers(conn, document_id, version_id, row["doc_type"], deps)
            layer = "save"
            created = save_results(conn, document_id, version_id, passed, tier, stats)
        except Exception as e:
            if isinstance(e, LayerFailed):
                layer, e = e.layer, e.cause
            try:
                conn.rollback()
                _fail(conn, document_id, back_to, layer=layer, error_type=type(e).__name__)
            except Exception as again:
                log.error("pipeline: document_id=%s could not be returned to %s (%s)", document_id, back_to.value,
                          type(again).__name__)
            # No traceback: an exception message can carry contract text.
            log.error("pipeline: document_id=%s version_id=%s failed in %s (%s) after %d ms", document_id, version_id,
                      layer, type(e).__name__, (time.monotonic() - started) * 1000)
            return {"outcome": "failed", "layer": layer, "error_type": type(e).__name__}
    ms = round((time.monotonic() - started) * 1000, 1)
    log.info("pipeline: document_id=%s version_id=%s findings=%d tier=%s ms=%.1f layers=%s", document_id, version_id,
             created, tier["review_tier"], ms, {k: v.get("ms") for k, v in stats.items()})
    return {"outcome": "pending_lawyer_review", "findings": created, "tier": tier["review_tier"], "ms": ms,
            "layers": stats}
