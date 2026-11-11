"""REVIEW_MODE=stub: the review that runs while the server has no model key.

It does what the real pipeline's last steps do (Layer 5 citation gate, R9 triage, one transaction that
saves the findings, audits and hands the document to the lawyer queue), but the findings are the fixed
sample ones from app/agents/fixtures.py. Nothing is read from the contract: no S3 read, no Gemini call.

Every sample finding's description starts with "[STUB] ", so the label shows wherever a finding is shown:
the lawyer's list and the client's view as well as the audit row (details.layers.stub_review.stub = true).
Do not change that prefix without changing where it is checked (tests/test_stub_review.py).
"""
import logging
import time
from typing import Callable

from fastapi import HTTPException

from app.agents import fixtures
from app.agents.citation_gate import screen_findings
from app.documents.states import DocState
from app.pipeline import runner
from app.pipeline.triage import triage

log = logging.getLogger(__name__)

# The fixtures are NDA-shaped, so no other contract type gets a stub review.
STUB_DOC_TYPES = frozenset({"nda"})


def require_stub_doc_type(doc: dict) -> None:
    if doc["doc_type"] not in STUB_DOC_TYPES:
        raise HTTPException(422, "While REVIEW_MODE=stub, reviews are only available for NDAs; "
                                 f"this document is '{doc['doc_type']}'")


def run_stub_review(document_id, version_id, from_state: str, *, connection: Callable | None = None) -> dict:
    """The background task, same contract as runner.run_pipeline: never raises, ends in
    pending_lawyer_review or back in from_state."""
    started = time.monotonic()
    back_to = DocState(from_state) if from_state in runner.REVIEWABLE else DocState.DRAFTED
    with (connection or runner._pool_connection)() as conn:
        layer = "setup"
        try:
            row = conn.execute("select doc_type, state from documents where id = %s", (document_id,)).fetchone()
            if row is None or row["state"] != DocState.UNDER_AI_REVIEW:
                log.warning("stub review: document_id=%s is not under_ai_review; nothing to do", document_id)
                return {"outcome": "skipped"}
            layer = "stub_review"
            gated = screen_findings(fixtures.sample_findings(), document_id,
                                    document=fixtures.sample_document_context(row["doc_type"]))
            tier = triage([p.finding for p in gated.passed])
            stats = {"stub_review": {"stub": True, "passed": len(gated.passed), "blocked": len(gated.blocked),
                                     "ms": round((time.monotonic() - started) * 1000, 1)}}
            layer = "save"
            created = runner.save_results(conn, document_id, version_id, gated.passed, tier, stats)
        except Exception as e:
            try:
                conn.rollback()
                runner._fail(conn, document_id, back_to, layer=layer, error_type=type(e).__name__)
            except Exception as again:
                log.error("stub review: document_id=%s could not be returned to %s (%s)", document_id,
                          back_to.value, type(again).__name__)
            log.error("stub review: document_id=%s failed in %s (%s)", document_id, layer, type(e).__name__)
            return {"outcome": "failed", "layer": layer, "error_type": type(e).__name__}
    log.info("stub review: document_id=%s version_id=%s findings=%d tier=%s", document_id, version_id, created,
             tier["review_tier"])
    return {"outcome": "pending_lawyer_review", "stub": True, "findings": created, "tier": tier["review_tier"]}
