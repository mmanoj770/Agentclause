"""
D5: Clause adaptation.

Adapts a retrieved clause to the deal facts (names, amounts, periods, places)
WITHOUT rewriting its legal substance.

How hallucination is prevented
The LLM never returns a rewritten clause. It may only propose small edits:
    {"find": "<exact text from the clause>", "replace": "<new text>", "fact": "<fact key>"}
Every edit is checked by deterministic code before it is applied:
  1. `find` must appear exactly once, verbatim, in the original clause, be short
     (<= 12 words), and not touch a cross-reference token like {{clause:x}}.
  2. `fact` must be one of the supplied deal facts, and `replace` must contain
     that fact's exact value.
  3. Apart from the fact value, `replace` may only reuse words that were already
     in `find` - so the model cannot introduce new words, obligations, numbers
     or statute citations (D7: citations only ever come from clause metadata).
  4. Legal operator words (shall, may, not, exclusive, indemnify, within, ...)
     must appear exactly as often in `replace` as in `find` - so the model
     cannot remove or add an obligation, a negation or a qualifier.
  5. The only words an edit may remove are placeholders ([City]), numbers,
     periods (days/months), currency and dates. Legal wording is never removed.
  6. Edits may not overlap.
Rejected edits are reported with a reason. If the model is unavailable or its
answer is unusable, the ORIGINAL clause text is kept unchanged and flagged.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from enum import StrEnum
from typing import Callable
from uuid import UUID

from pydantic import BaseModel, Field

from app.clauses.models import FavouredParty, VerificationStatus
from app.drafting.retrieval import RetrievedClause
from app.drafting.schemas import DealFacts
from app.gemini import GeminiError, generate_json

MAX_EDITS = 20
MAX_FIND_CHARS = 80
MAX_FIND_WORDS = 12
MAX_REPLACE_CHARS = 250

# Words that carry legal meaning. An edit must keep their counts unchanged.
PROTECTED_WORDS = frozenset({
    "shall", "may", "must", "will", "should", "can", "cannot",
    "not", "no", "nor", "never", "neither", "none", "only", "solely", "sole",
    "any", "all", "each", "every", "either", "both", "other",
    "and", "or", "if", "unless", "except", "subject", "provided", "notwithstanding",
    "without", "with", "within", "before", "after", "prior", "until", "upon",
    "least", "more", "less", "maximum", "minimum", "exceed", "exceeding",
    "exclusive", "exclusively", "non", "irrevocable", "irrevocably", "perpetual",
    "indemnify", "indemnity", "liable", "liability", "terminate", "termination",
    "written", "reasonable", "reasonably", "best", "including", "includes",
    "jointly", "severally", "waive", "waiver", "consent", "breach",
})

# The only kinds of words an edit may remove: numbers and their units, currency,
# dates, and words inside a bracketed placeholder like [City]. Anything else in
# a clause is legal wording and must survive the edit untouched.
REPLACEABLE_WORDS = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety", "hundred", "thousand", "lakh", "lakhs", "crore", "crores",
    "million", "billion",
    "day", "days", "week", "weeks", "month", "months", "year", "years", "hour", "hours",
    "business", "calendar", "working",
    "inr", "rs", "rupee", "rupees", "usd", "dollar", "dollars", "per", "cent", "percent",
    "january", "february", "march", "april", "june", "july", "august",  # "may" is a legal operator
    "september", "october", "november", "december",
})

WORD_RE = re.compile(r"[a-z]+|\d+(?:[.,]\d+)*")
XREF_RE = re.compile(r"\{\{[^{}]*\}\}")
PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{1,60}\]")

SYSTEM_PROMPT = """You fill in deal-specific facts in a legal clause that a lawyer has already approved.
You must NOT change the legal meaning of the clause in any way.

You never rewrite the clause. You only propose small find-and-replace edits where
a deal fact clearly belongs:
- a bracketed placeholder such as [City] or [Amount] that matches a fact
- a generic period, amount or date that the facts give a value for (for example,
  the notice period in the clause when the facts give "notice_period")

Rules:
- "find" must be copied EXACTLY from the clause (same characters, same case), and
  be as short as possible (a few words).
- "replace" must contain the fact's exact value, and otherwise only words from "find".
- "fact" must be the key of the fact you used.
- Keep generic references such as "each party", "either party", "the other party" unchanged.
- Never add, remove or change obligations, conditions, negations, liability, or
  statute references. Never invent values that are not in the facts.
- If no fact clearly belongs anywhere, return no edits. Doing nothing is always safe.

Return JSON only, in this exact shape:
{"edits": [{"find": "...", "replace": "...", "fact": "..."}]}"""


class AdaptationStatus(StrEnum):
    adapted = "adapted"                    # at least one validated edit applied
    unchanged = "unchanged"                # model proposed no edits; text is the original
    fallback_original = "fallback_original"  # model failed or all edits rejected; original kept


class Edit(BaseModel):
    find: str
    replace: str
    fact: str


class RejectedEdit(BaseModel):
    edit: dict
    reason: str


class AdaptedClause(BaseModel):
    clause_id: UUID
    clause_type: str
    title: str
    favoured_party: FavouredParty
    statute_refs: list[str]
    version: int
    verification_status: VerificationStatus
    original_content: str
    content: str
    status: AdaptationStatus
    edits_applied: list[Edit] = Field(default_factory=list)
    edits_rejected: list[RejectedEdit] = Field(default_factory=list)
    unresolved_placeholders: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text.casefold())


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _check_edit(raw, original: str, facts: dict[str, str], xref_spans) -> tuple[Edit, int] | str:
    """Return (edit, start_index) if the edit is safe, else a rejection reason."""
    if not isinstance(raw, dict):
        return "edit is not an object"
    find, replace, fact = raw.get("find"), raw.get("replace"), raw.get("fact")
    if not all(isinstance(x, str) for x in (find, replace, fact)):
        return "find, replace and fact must all be strings"
    if not find.strip() or not replace.strip():
        return "find and replace cannot be empty"
    if len(find) > MAX_FIND_CHARS or len(_words(find)) > MAX_FIND_WORDS:
        return "find is too long; edits must be small"
    if len(replace) > MAX_REPLACE_CHARS:
        return "replace is too long"

    occurrences = original.count(find)
    if occurrences == 0:
        return "find text does not appear verbatim in the clause"
    if occurrences > 1:
        return "find text appears more than once (ambiguous)"
    start = original.index(find)
    end = start + len(find)
    if any(start < x_end and x_start < end for x_start, x_end in xref_spans):
        return "edit touches a cross-reference token"

    if fact not in facts:
        return f"unknown fact '{fact}'"
    value = facts[fact]
    norm_replace, norm_value = _norm(replace), _norm(value)
    if norm_value not in norm_replace:
        return f"replace does not contain the exact value of fact '{fact}'"

    # Everything in `replace` other than the fact value must come from `find`.
    leftover = norm_replace.replace(norm_value, " ", 1)
    extra = Counter(_words(leftover)) - Counter(_words(find))
    if extra:
        return f"replace introduces words not in the facts: {sorted(extra)}"

    # Legal operator words must be preserved exactly.
    find_ops = Counter(w for w in _words(find) if w in PROTECTED_WORDS)
    kept_ops = Counter(w for w in _words(leftover) if w in PROTECTED_WORDS)
    if find_ops != kept_ops:
        changed = sorted(set(find_ops) | set(kept_ops))
        return f"edit would change legal operator words: {changed}"

    # Only placeholders, numbers, periods, currency and dates may be removed.
    placeholder_words = {w for p in PLACEHOLDER_RE.findall(find) for w in _words(p)}
    removed = Counter(_words(find)) - Counter(_words(leftover))
    not_replaceable = sorted(
        w for w in removed
        if not (w[0].isdigit() or w in REPLACEABLE_WORDS or w in placeholder_words)
    )
    if not_replaceable:
        return f"edit would remove legal wording: {not_replaceable}"

    return Edit(find=find, replace=replace, fact=fact), start


def _build_prompt(clause: RetrievedClause, facts: dict[str, str]) -> str:
    return (
        "CLAUSE (approved text - do not change its meaning):\n"
        f"<<<\n{clause.content}\n>>>\n\n"
        "DEAL FACTS (the only values you may insert):\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=2)}\n\n"
        "Return the JSON edits now."
    )


def adapt_clause(
    clause: RetrievedClause,
    deal: DealFacts,
    *,
    llm: Callable[..., dict] = generate_json,
) -> AdaptedClause:
    """Adapt one clause to the deal. Never raises for model/API problems."""
    original = clause.content
    facts = deal.allowed_facts()
    base = dict(
        clause_id=clause.clause_id,
        clause_type=clause.clause_type,
        title=clause.title,
        favoured_party=clause.favoured_party,
        statute_refs=list(clause.statute_refs),
        version=clause.version,
        verification_status=clause.verification_status,
        original_content=original,
    )
    warnings: list[str] = []

    try:
        answer = llm(_build_prompt(clause, facts), system=SYSTEM_PROMPT)
        raw_edits = answer.get("edits") if isinstance(answer, dict) else None
        if not isinstance(raw_edits, list):
            raise GeminiError("model answer has no 'edits' list")
    except (GeminiError, ValueError) as exc:
        return _finish(base, original, AdaptationStatus.fallback_original, [], [],
                       [f"Adaptation skipped, original clause kept: {exc}"])

    if len(raw_edits) > MAX_EDITS:
        warnings.append(f"Model proposed {len(raw_edits)} edits; only the first {MAX_EDITS} were considered.")
        raw_edits = raw_edits[:MAX_EDITS]

    xref_spans = [(m.start(), m.end()) for m in XREF_RE.finditer(original)]
    accepted: list[tuple[int, Edit]] = []
    rejected: list[RejectedEdit] = []
    for raw in raw_edits:
        checked = _check_edit(raw, original, facts, xref_spans)
        if isinstance(checked, str):
            rejected.append(RejectedEdit(edit=raw if isinstance(raw, dict) else {"value": repr(raw)},
                                         reason=checked))
            continue
        edit, start = checked
        end = start + len(edit.find)
        if any(start < s + len(e.find) and s < end for s, e in accepted):
            rejected.append(RejectedEdit(edit=raw, reason="overlaps another edit"))
            continue
        accepted.append((start, edit))

    # Apply from the end so earlier offsets stay valid.
    content = original
    for start, edit in sorted(accepted, key=lambda t: t[0], reverse=True):
        content = content[:start] + edit.replace + content[start + len(edit.find):]

    if rejected:
        warnings.append(f"{len(rejected)} proposed edit(s) rejected by safety checks.")
    if accepted:
        status = AdaptationStatus.adapted
    elif rejected:
        status = AdaptationStatus.fallback_original
        warnings.append("No proposed edit passed the safety checks; original clause kept.")
    else:
        status = AdaptationStatus.unchanged

    applied = [e for _, e in sorted(accepted, key=lambda t: t[0])]
    return _finish(base, content, status, applied, rejected, warnings)


def _finish(base, content, status, applied, rejected, warnings) -> AdaptedClause:
    placeholders = PLACEHOLDER_RE.findall(content)
    if placeholders:
        warnings = warnings + [f"Unfilled placeholder(s) remain: {', '.join(placeholders)}"]
    return AdaptedClause(
        **base,
        content=content,
        status=status,
        edits_applied=applied,
        edits_rejected=rejected,
        unresolved_placeholders=placeholders,
        warnings=warnings,
    )
