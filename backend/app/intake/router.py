from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, get_current_user
from app.documents.states import STARTUP
from app.intake import service
from app.intake.service import (IntakeError, IntakeNotConfiguredError, IntakeUnavailableError,
                                NotAContractError)
from app.schemas.normalized_document import DocumentType, NormalizedDocument

router = APIRouter(prefix="/intake", tags=["intake"])


class NormalizeRequest(BaseModel):
    contract_text: str = Field(min_length=1, max_length=500_000)
    contract_type_id: DocumentType


@router.post("/normalize", response_model=NormalizedDocument)
def normalize_contract(body: NormalizeRequest,
                       user: CurrentUser = Depends(get_current_user)) -> NormalizedDocument:
    """R2: extract parties, dates, jurisdiction and clauses from contract text.

    Sync on purpose: the Gemini client blocks, so FastAPI runs this in its thread pool."""
    # Same rule as POST /documents: a startup user must belong to an organization.
    if user.role == STARTUP and user.org_id is None:
        raise HTTPException(400, "Your account is not linked to an organization yet")
    try:
        return service.normalize(body.contract_text, body.contract_type_id.value)
    except NotAContractError as e:
        raise HTTPException(422, str(e))
    except (IntakeNotConfiguredError, IntakeUnavailableError) as e:
        raise HTTPException(503, str(e))
    except IntakeError as e:
        raise HTTPException(502, str(e))
