from functools import lru_cache

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import CurrentUser, get_current_user
from app.intake.service import IntakeError, IntakeNotConfiguredError, IntakeService, NotAContractError
from app.schemas.normalized_document import NormalizedDocument

router = APIRouter(prefix="/intake", tags=["intake"])


@lru_cache
def get_service() -> IntakeService:
    return IntakeService()


class NormalizeRequest(BaseModel):
    contract_text: str = Field(min_length=1, max_length=500_000)


@router.post("/normalize", response_model=NormalizedDocument)
async def normalize_contract(body: NormalizeRequest,
                             user: CurrentUser = Depends(get_current_user),
                             service: IntakeService = Depends(get_service)) -> NormalizedDocument:
    """R2: extract parties, dates, document type, jurisdiction and clause kinds from contract text."""
    try:
        return await service.normalize(body.contract_text)
    except NotAContractError as e:
        raise HTTPException(422, str(e))
    except IntakeNotConfiguredError as e:
        raise HTTPException(503, str(e))
    except IntakeError as e:
        raise HTTPException(502, str(e))
    except anthropic.AuthenticationError:
        raise HTTPException(503, "Contract extraction is not configured on this server.")
    except anthropic.RateLimitError:
        raise HTTPException(503, "Contract extraction is busy. Try again shortly.")
    except (anthropic.APIStatusError, anthropic.APIConnectionError):
        raise HTTPException(502, "Contract extraction is unavailable right now.")
