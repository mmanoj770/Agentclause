import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, require_role
from app.documents.states import STARTUP
from app.intake import service
from app.intake.limits import MAX_CONTRACT_CHARS, limiter
from app.intake.service import (IntakeError, IntakeNotConfiguredError, IntakeUnavailableError,
                                NotAContractError)
from app.schemas.normalized_document import DocumentType, NormalizedDocument

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intake", tags=["intake"])


class NormalizeRequest(BaseModel):
    contract_text: str = Field(min_length=1, max_length=MAX_CONTRACT_CHARS)
    contract_type_id: DocumentType


@router.post("/normalize", response_model=NormalizedDocument)
def normalize_contract(body: NormalizeRequest,
                       user: CurrentUser = Depends(require_role(STARTUP))) -> NormalizedDocument:
    """R2: extract parties, dates, jurisdiction and clauses from contract text.

    Startup users only. Sync on purpose: the Gemini client blocks, so FastAPI runs this in its thread
    pool. Each request can trigger up to 3 model calls, so the size cap and the per-user rate limit
    (app/intake/limits.py) are the cost controls. Usage is logged as user id, size and outcome:
    never the contract text.
    """
    # Same rule as POST /documents: a startup user must belong to an organization.
    if user.org_id is None:
        raise HTTPException(400, "Your account is not linked to an organization yet")
    if not limiter.allow(user.id):
        raise HTTPException(429, "Too many requests. Try again shortly.", headers={"Retry-After": "60"})
    size = len(body.contract_text)
    outcome = "error"
    try:
        result = service.normalize(body.contract_text, body.contract_type_id.value)
        outcome = "ok"
        return result
    except NotAContractError as e:
        outcome = "not_a_contract"
        raise HTTPException(422, str(e))
    except IntakeNotConfiguredError as e:
        outcome = "not_configured"
        raise HTTPException(503, str(e))
    except IntakeUnavailableError as e:
        outcome = "unavailable"
        raise HTTPException(503, str(e))
    except IntakeError as e:
        outcome = "intake_error"
        raise HTTPException(502, str(e))
    finally:
        logger.info("intake.normalize user=%s chars=%d outcome=%s", user.id, size, outcome)
