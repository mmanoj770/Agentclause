from enum import StrEnum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class VerificationStatus(StrEnum):
    staging  = "staging"
    verified = "verified"


class FavouredParty(StrEnum):
    party_a = "party_a"
    party_b = "party_b"
    neutral = "neutral"


class ClauseRecord(BaseModel):
    clause_id:           UUID               = Field(default_factory=uuid4)
    clause_type:         str
    contract_types:      list[str]
    favoured_party:      FavouredParty
    statute_refs:        list[str]          = []
    version:             int                = 1
    verification_status: VerificationStatus = VerificationStatus.staging
    content:             str
    title:               str
    notes:               Optional[str]      = None
    verified_by:         Optional[str]      = None

    model_config = {"use_enum_values": True}

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Clause content cannot be empty")
        return v

    @field_validator("contract_types")
    @classmethod
    def at_least_one_contract_type(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Must specify at least one contract type")
        return v
