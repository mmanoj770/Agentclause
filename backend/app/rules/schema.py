"""Rule file format (R4) and loader.

A rule is one JSON file in a rules directory. See README.md in this folder for the format.
"""
import ast
import json
import re
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.rules.clauses import CLAUSES
from app.schemas.finding import CitationType, Severity

INTERNAL = "Internal"
# Matches migration 18's STATUTORY backfill pattern once rendered: "<Act>, <year>, s. <n>".
_STATUTE = re.compile(r"^.+,\s*\d{4}$")
_SECTION = re.compile(r"^\d+[A-Z]?(\(\w+\))*$")
CONDITIONS = {"missing_clause", "contains_text"}


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class RuleError(ValueError):
    """A rule file that can't be used. The message names the file and what is wrong."""


def parse_condition(condition: str) -> tuple[str, tuple[str, ...]]:
    """Parse `name('arg', ...)` into (name, args). Only known names and string arguments are allowed."""
    try:
        node = ast.parse(condition.strip(), mode="eval").body
    except SyntaxError as e:
        raise ValueError(f"condition is not a function call: {condition!r}") from e
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)) or node.keywords:
        raise ValueError(f"condition must look like name('arg', ...): {condition!r}")
    name = node.func.id
    if name not in CONDITIONS:
        raise ValueError(f"unknown condition {name!r}; allowed: {sorted(CONDITIONS)}")
    if not node.args or not all(isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.strip()
                                for a in node.args):
        raise ValueError(f"{name}() takes one or more non-empty string arguments")
    args = tuple(a.value.strip() for a in node.args)
    if name == "missing_clause":
        if len(args) != 1:
            raise ValueError("missing_clause() takes exactly one clause id")
        if args[0] not in CLAUSES:
            raise ValueError(f"unknown clause id {args[0]!r}; known: {sorted(CLAUSES)}")
    return name, args


class Rule(BaseModel):
    """One rule. Its finding fires when `condition` holds for a contract of a type in `applies_to`."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=100,
                         description="Visible rule ID; becomes the finding's rule_applied.")
    statute: str = Field(min_length=1,
                         description="Act with its year, e.g. \"Indian Contract Act, 1872\", or "
                                     "\"Internal\" for a house baseline that no statute backs.")
    section: str = Field(min_length=1,
                         description="Section number (\"27\") for a statute; a short label for Internal.")
    applies_to: list[str] = Field(min_length=1, description="contract_types codes, e.g. [\"nda\"].")
    condition: str = Field(description="missing_clause('<clause id>') or contains_text('<phrase>', ...).")
    severity: Severity
    description: str | None = Field(default=None, min_length=1,
                                    description="What the finding says. Generated from the condition if omitted.")
    remedy_suggested: str = Field(min_length=1)
    version: int = Field(ge=1, description="Starts at 1; a changed rule is a new file with the next version.")
    effective_from: date
    effective_to: date | None = Field(default=None, description="Last day in force (inclusive). None = open-ended.")
    superseded_by: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*(@[1-9][0-9]*)?$",
                                      description="The rule (\"RULE_ID\" or \"RULE_ID@<version>\") that replaces this one.")
    verification_status: VerificationStatus

    @field_validator("version", mode="before")
    @classmethod
    def _integer_version(cls, v: Any) -> Any:
        # Pydantic would accept "1" or 1.0; a version is written as a plain integer.
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("version must be an integer, e.g. 1")
        return v

    @field_validator("severity", "verification_status", mode="before")
    @classmethod
    def _lowercase(cls, v: Any) -> Any:
        return v.lower() if isinstance(v, str) else v

    @field_validator("applies_to")
    @classmethod
    def _codes(cls, v: list[str]) -> list[str]:
        codes = [c.strip().lower() for c in v]
        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", c) for c in codes):
            raise ValueError("applies_to must hold contract type codes like 'nda'")
        return codes

    @field_validator("condition")
    @classmethod
    def _condition(cls, v: str) -> str:
        parse_condition(v)
        return v

    @model_validator(mode="after")
    def _dates(self) -> "Rule":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to is before effective_from")
        if self.superseded_by in (self.rule_id, self.versioned_id):
            raise ValueError("a rule cannot be superseded by itself")
        return self

    @model_validator(mode="after")
    def _citation_shape(self) -> "Rule":
        if self.statute != INTERNAL:
            if not _STATUTE.match(self.statute):
                raise ValueError("statute must name the Act and its year, e.g. 'Indian Contract Act, 1872' "
                                 "(or be 'Internal')")
            if not _SECTION.match(self.section):
                raise ValueError("section must be a section number like '27' or '73(1)' for a statute")
        return self

    @property
    def citation(self) -> str:
        """The finding's citation, shaped so migration 18 classifies it (STATUTORY or INTERNAL_BASELINE)."""
        if self.statute == INTERNAL:
            return f"Internal: {self.section}"
        return f"{self.statute}, s. {self.section}"

    @property
    def citation_type(self) -> CitationType:
        return CitationType.INTERNAL_BASELINE if self.statute == INTERNAL else CitationType.STATUTORY

    @property
    def verified(self) -> bool:
        return self.verification_status is VerificationStatus.VERIFIED

    @property
    def versioned_id(self) -> str:
        """What a finding records as rule_applied, e.g. "ICA_S27_RESTRAINT_OF_TRADE@1"."""
        return f"{self.rule_id}@{self.version}"

    def in_force_on(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None or day <= self.effective_to)

    def overlaps(self, other: "Rule") -> bool:
        """True if the two date ranges share a day (both ends inclusive)."""
        never = date.max
        return (self.effective_from <= (other.effective_to or never)
                and other.effective_from <= (self.effective_to or never))


def base_rule_id(rule_applied: str) -> str:
    """"ICA_S27_RESTRAINT_OF_TRADE@1" -> "ICA_S27_RESTRAINT_OF_TRADE". Unversioned IDs come back as they are."""
    return rule_applied.split("@", 1)[0]


class RuleValidator:
    """Validates rule data and rule files, raising RuleError with a readable message."""

    @staticmethod
    def validate(data: Any, source: str = "<rule>") -> Rule:
        if not isinstance(data, dict):
            raise RuleError(f"{source}: a rule file must hold one JSON object")
        try:
            return Rule.model_validate(data)
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'rule'}: {err['msg']}" for err in e.errors())
            raise RuleError(f"{source}: {problems}") from e

    @classmethod
    def validate_file(cls, path: Path) -> Rule:
        try:
            data = json.loads(Path(path).read_text())
        except json.JSONDecodeError as e:
            raise RuleError(f"{path.name}: not valid JSON ({e.msg}, line {e.lineno})") from e
        return cls.validate(data, path.name)


class RuleLoader:
    """Loads every *.json rule in a directory. Any bad file stops the load: rules never fail silently.

    A rule_id may have several versions, one file each, whose effective dates must not overlap. load()
    returns, per rule_id, the version in force on `on` (default today). strict=True (the default) then
    keeps verified rules only; it never falls back to an older verified version.
    """

    def __init__(self, directory: Path, strict: bool = True, on: date | None = None):
        self.directory = Path(directory)
        self.strict = strict
        self.on = on

    def load_all(self) -> list[Rule]:
        """Every version of every rule, after checking versions and dates are consistent."""
        versions: dict[str, list[tuple[Rule, str]]] = {}
        for path in sorted(self.directory.glob("*.json")):
            rule = RuleValidator.validate_file(path)
            for other, other_file in versions.get(rule.rule_id, []):
                if other.version == rule.version:
                    raise RuleError(f"{path.name}: duplicate rule_id {rule.rule_id} version {rule.version} "
                                    f"(also in {other_file})")
                if other.overlaps(rule):
                    raise RuleError(f"{path.name}: {rule.versioned_id} is in force on dates that overlap "
                                    f"{other.versioned_id} in {other_file}")
            versions.setdefault(rule.rule_id, []).append((rule, path.name))
        known = set(versions) | {r.versioned_id for entries in versions.values() for r, _ in entries}
        for entries in versions.values():
            for rule, name in entries:
                if rule.superseded_by and rule.superseded_by not in known:
                    raise RuleError(f"{name}: superseded_by names unknown rule {rule.superseded_by}")
        return [rule for entries in versions.values() for rule, _ in entries]

    def load(self) -> list[Rule]:
        day = self.on or date.today()
        in_force = [r for r in self.load_all() if r.in_force_on(day)]
        return [r for r in in_force if r.verified or not self.strict]
