"""Shared input schemas for the Drafting Agent."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

TERM_KEY = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
RESERVED_KEYS = {
    "party_a_name", "party_a_short_name", "party_b_name", "party_b_short_name",
    "effective_date", "governing_law", "jurisdiction_city",
}


def _non_empty(v: str | None, field: str, max_len: int) -> str | None:
    if v is None:
        return None
    v = " ".join(v.split())  # collapse stray whitespace/newlines
    if not v:
        raise ValueError(f"{field} cannot be empty")
    if len(v) > max_len:
        raise ValueError(f"{field} is longer than {max_len} characters")
    return v


class Party(BaseModel):
    name: str                       # full legal name, e.g. "Quenta Technologies Private Limited"
    short_name: str | None = None   # defined term, e.g. "Quenta"
    description: str | None = None  # e.g. "a company incorporated under the laws of India"

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _non_empty(v, "party name", 200)

    @field_validator("short_name")
    @classmethod
    def _short(cls, v):
        return _non_empty(v, "short name", 60)

    @field_validator("description")
    @classmethod
    def _desc(cls, v):
        return _non_empty(v, "party description", 400)


class DealFacts(BaseModel):
    """
    The deal-specific facts a clause may be adapted to. These are the ONLY new
    values D5 is allowed to put into a clause.

    terms: other concrete values keyed by a snake_case name, e.g.
        {"notice_period": "60 days", "payment_period": "30 days", "fee": "INR 5,00,000"}
    """
    contract_type: str
    party_a: Party
    party_b: Party
    effective_date: date | None = None
    governing_law: str | None = None       # e.g. "India"
    jurisdiction_city: str | None = None   # e.g. "Bengaluru"
    terms: dict[str, str] = Field(default_factory=dict)

    @field_validator("contract_type")
    @classmethod
    def _ct(cls, v):
        return _non_empty(v, "contract_type", 60)

    @field_validator("governing_law", "jurisdiction_city")
    @classmethod
    def _place(cls, v):
        return _non_empty(v, "value", 100)

    @field_validator("terms")
    @classmethod
    def _terms(cls, v: dict[str, str]):
        if len(v) > 40:
            raise ValueError("too many terms (max 40)")
        cleaned = {}
        for key, value in v.items():
            if not TERM_KEY.match(key):
                raise ValueError(f"term key '{key}' must be snake_case (a-z, 0-9, _)")
            if key in RESERVED_KEYS:
                raise ValueError(f"term key '{key}' is reserved; use the dedicated field")
            if not isinstance(value, str):
                raise ValueError(f"term '{key}' must be a string, e.g. \"60 days\"")
            cleaned[key] = _non_empty(value, f"term '{key}'", 200)
        return cleaned

    @model_validator(mode="after")
    def _distinct_parties(self):
        if self.party_a.name.casefold() == self.party_b.name.casefold():
            raise ValueError("party_a and party_b must be different")
        a, b = self.party_a.short_name, self.party_b.short_name
        if a and b and a.casefold() == b.casefold():
            raise ValueError("party short names must be different")
        return self

    def allowed_facts(self) -> dict[str, str]:
        """Every concrete value D5 may insert, keyed by name."""
        facts: dict[str, str] = {
            "party_a_name": self.party_a.name,
            "party_b_name": self.party_b.name,
        }
        if self.party_a.short_name:
            facts["party_a_short_name"] = self.party_a.short_name
        if self.party_b.short_name:
            facts["party_b_short_name"] = self.party_b.short_name
        if self.effective_date:
            facts["effective_date"] = format_date(self.effective_date)
        if self.governing_law:
            facts["governing_law"] = self.governing_law
        if self.jurisdiction_city:
            facts["jurisdiction_city"] = self.jurisdiction_city
        facts.update(self.terms)
        return facts


def format_date(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"
