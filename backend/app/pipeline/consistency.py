"""Layer 3 cross-clause consistency (R6): two clauses that state the same fact differently.

    run_consistency(doc)  ->  ConsistencyResult(findings, facts)

Each topic has a small extractor that reads one fact per sentence from a numbered clause:

    governing_law       "governed by the laws of India"                 -> "india"
    jurisdiction        "the courts at Pune have exclusive jurisdiction" -> "pune"
    payment_period      "shall pay ... within 30 days"                  -> 30 (days)
    termination_notice  "terminate ... on 60 days' written notice"       -> 60 (days)
    agreement_term      "remain in force for three years"                -> 36 (months)

When two different clauses give the same topic different values, the first clause stating each value is
paired with the first clause of the topic, and each pair becomes a CONSISTENCY finding citing
"Internal: Clause <a> vs Clause <b>", the shape the Layer 5 gate resolves on Layer 3 (both clauses must
be in the version's clause manifest). Two values inside ONE clause can't be cited that way and are only
counted in the log.

Matching is keyword-based. It will miss unusual wording, and two periods that legitimately differ
(a deposit and a balance) will be flagged: every finding needs a reader. Severities are in
config/consistency.json (PLACEHOLDER; findings capped at LOW while it is). Logs carry counts only.
"""
import json
import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.pipeline.asymmetry import split_clauses
from app.schemas.finding import CitationType, Finding, Layer, Severity
from app.schemas.normalized_document import NormalizedDocument

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config" / "consistency.json"
TOPICS = ("governing_law", "jurisdiction", "payment_period", "termination_notice", "agreement_term")


class ConsistencyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1)
    note: str | None = None
    severity: dict[str, Severity]

    @model_validator(mode="after")
    def _all_topics(self) -> "ConsistencyConfig":
        if set(self.severity) != set(TOPICS):
            raise ValueError(f"severity must name exactly these topics: {sorted(TOPICS)}")
        return self

    @property
    def is_placeholder(self) -> bool:
        return self.status == "PLACEHOLDER"


def load_config(path: Path = CONFIG_PATH) -> ConsistencyConfig:
    return ConsistencyConfig.model_validate(json.loads(Path(path).read_text()))


@lru_cache
def _default_config() -> ConsistencyConfig:
    return load_config()


# --- extractors -------------------------------------------------------------------------------

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "eighteen": 18, "twenty": 20, "thirty": 30,
          "forty-five": 45, "sixty": 60, "ninety": 90}
_NUMBER = r"(\d{1,4}|" + "|".join(sorted(map(re.escape, _WORDS), key=len, reverse=True)) + r")(?:\s*\(\s*(\d{1,4})\s*\))?"
_SENTENCE = re.compile(r"[^.;]+(?:[.;]|$)")


def _amount(word: str, digits: str | None) -> int:
    """"sixty (60)" -> 60, "60" -> 60, "sixty" -> 60. Digits in brackets win when both are given."""
    if digits:
        return int(digits)
    return int(word) if word.isdigit() else _WORDS[word.lower()]


_GOVERNING_LAW = re.compile(r"\b(?:governed\s+by|construed\s+in\s+accordance\s+with)\s+the\s+laws?\s+of\s+"
                            r"(?:the\s+(?:state|republic)\s+of\s+)?([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)")
_COURTS = re.compile(r"\bcourts?\s+(?:at|in|of)\s+([A-Z][A-Za-z]+)")
_DAYS = re.compile(rf"\b{_NUMBER}\s*(?:[A-Za-z-]+\s+){{0,2}}?days?\b", re.IGNORECASE)
_TERM = re.compile(rf"\bremain\s+in\s+(?:full\s+)?(?:force|effect)\s+for\s+(?:a\s+(?:period|term)\s+of\s+)?"
                   rf"{_NUMBER}\s+(years?|months?)\b", re.IGNORECASE)


def _facts_in(sentence: str) -> list[tuple[str, str | int, str]]:
    """(topic, value, unit) for each fact this sentence states."""
    facts = []
    if m := _GOVERNING_LAW.search(sentence):
        facts.append(("governing_law", m.group(1).lower(), ""))
    if re.search(r"\bjurisdiction\b", sentence, re.IGNORECASE) and (m := _COURTS.search(sentence)):
        facts.append(("jurisdiction", m.group(1).lower(), ""))
    lower = sentence.lower()
    if re.search(r"\bpa(?:y|yments?|yable|id)\b", lower) and not re.search(r"\binterest\b", lower):
        if days := _DAYS.search(sentence):
            facts.append(("payment_period", _amount(days.group(1), days.group(2)), "days"))
    if re.search(r"\b(terminat\w*|end\s+this\s+agreement)\b", lower) and "notice" in lower:
        if days := _DAYS.search(sentence):
            facts.append(("termination_notice", _amount(days.group(1), days.group(2)), "days"))
    if m := _TERM.search(sentence):
        n = _amount(m.group(1), m.group(2))
        facts.append(("agreement_term", n * 12 if m.group(3).lower().startswith("year") else n, "months"))
    return facts


@dataclass(frozen=True)
class Fact:
    topic: str
    clause_number: str
    value: str | int
    unit: str


def extract_facts(text: str) -> list[Fact]:
    facts = []
    for clause in split_clauses(text):
        for sentence in (m.group(0) for m in _SENTENCE.finditer(clause.text)):
            facts += [Fact(t, clause.number, v, u) for t, v, u in _facts_in(sentence)]
    return facts


# --- findings ---------------------------------------------------------------------------------

LABELS = {"governing_law": "governing law", "jurisdiction": "courts with jurisdiction",
          "payment_period": "payment period", "termination_notice": "notice period for termination",
          "agreement_term": "term of the agreement"}
REMEDIES = {"governing_law": "Choose one governing law and state it in one clause only.",
            "jurisdiction": "Choose one seat for the courts and refer to it everywhere else.",
            "payment_period": "Use one payment period, or say clearly which payment each period applies to.",
            "termination_notice": "Use one notice period, or say clearly which ground of termination each applies to.",
            "agreement_term": "State the term once and refer back to that clause."}


def _show(fact: Fact) -> str:
    if fact.unit == "months":
        return f"{fact.value // 12} years" if fact.value % 12 == 0 else f"{fact.value} months"
    return f"{fact.value} {fact.unit}".strip() if fact.unit else str(fact.value).title()


@dataclass
class ConsistencyResult:
    findings: list[Finding]
    facts: list[Fact]


def run_consistency(doc: NormalizedDocument, *, config: ConsistencyConfig | None = None) -> ConsistencyResult:
    started = time.monotonic()
    config = config or _default_config()
    facts = extract_facts(doc.full_text)
    findings, same_clause = [], 0
    for topic in TOPICS:
        stated = [f for f in facts if f.topic == topic]
        if not stated:
            continue
        first = stated[0]
        if len({f.value for f in stated if f.clause_number == first.clause_number}) > 1:
            same_clause += 1                                   # two values in one clause: not citable as a pair
        seen = {first.value}
        for f in stated[1:]:
            if f.value in seen or f.clause_number == first.clause_number:
                continue
            seen.add(f.value)
            severity = Severity.LOW if config.is_placeholder else config.severity[topic]
            findings.append(Finding(
                layer=Layer.CONSISTENCY,
                severity=severity,
                clause_reference=f"Clause {first.clause_number}",
                description=(f"Clause {first.clause_number} and Clause {f.clause_number} give different "
                             f"{LABELS[topic]}: {_show(first)} and {_show(f)}."),
                rule_applied=f"R6_CONFLICT_{topic.upper()}",
                remedy_suggested=REMEDIES[topic],
                citation=f"Internal: Clause {first.clause_number} vs Clause {f.clause_number}",
                citation_type=CitationType.INTERNAL_BASELINE,
            ))
    log.info("consistency: contract_type=%s facts=%d findings=%d same_clause_conflicts=%d ms=%d",
             doc.document_type.value, len(facts), len(findings), same_clause, (time.monotonic() - started) * 1000)
    return ConsistencyResult(findings=findings, facts=facts)
