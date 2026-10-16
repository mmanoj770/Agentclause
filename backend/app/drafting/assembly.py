"""
D6: Document assembly.

Composes adapted clauses (D5) into one contract with:
- a preamble naming the parties and their defined short names
- a numbered Definitions clause (when there is anything to define)
- numbered clauses, with multi-paragraph clauses numbered N.1, N.2, ...
- cross-references: a clause may contain {{clause:<clause_type>}}, which is
  replaced with "Clause N" for the clause of that type in this document.
  An unknown reference is never guessed: it is rendered as
  [UNRESOLVED REFERENCE: x] and reported in warnings.
- statute citations attached from clause metadata (D7)

assemble_document() returns a structured DraftDocument. Do not render it
directly for anyone: always go through app.drafting.guard.render_for (D8),
which decides whether it may be shown to a lawyer.
"""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel, Field

from app.clauses.models import VerificationStatus
from app.drafting.adaptation import AdaptationStatus, AdaptedClause, Edit
from app.drafting.citations import Citation, resolve_citations
from app.drafting.schemas import DealFacts, format_date

XREF_RE = re.compile(r"\{\{\s*clause\s*:\s*([a-z0-9_]+)\s*\}\}")
ANY_TOKEN_RE = re.compile(r"\{\{[^{}]*\}\}")
DEFINITIONS_TYPE = "definitions"
SMALL_WORDS = {"a", "an", "and", "for", "in", "of", "on", "or", "the", "to"}


class Definition(BaseModel):
    term: str
    meaning: str


class DraftClause(BaseModel):
    number: int
    heading: str
    clause_id: UUID
    clause_type: str
    version: int
    verification_status: VerificationStatus
    paragraphs: list[str]
    citations: list[Citation] = Field(default_factory=list)
    unresolved_citations: list[str] = Field(default_factory=list)
    adaptation_status: AdaptationStatus
    edits_applied: list[Edit] = Field(default_factory=list)
    unresolved_placeholders: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DraftDocument(BaseModel):
    title: str
    contract_type: str
    preamble: str
    definitions: list[Definition] = Field(default_factory=list)
    definitions_number: int | None = None
    clauses: list[DraftClause] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def default_heading(clause_type: str) -> str:
    words = clause_type.replace("-", "_").split("_")
    out = []
    for i, w in enumerate(w for w in words if w):
        out.append(w if (i > 0 and w in SMALL_WORDS) else w.capitalize())
    return " ".join(out) or "Clause"


def _party_line(n: int, name: str, description: str | None, short: str | None) -> str:
    line = f"({n}) {name}"
    if description:
        line += f", {description}"
    if short:
        line += f' ("{short}")'
    return line


def _uses_term(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def assemble_document(
    title: str,
    deal: DealFacts,
    clauses: list[AdaptedClause],
    *,
    headings: dict[str, str] | None = None,
    definitions: dict[str, str] | None = None,
) -> DraftDocument:
    """
    Build the draft. Clause order is the order of `clauses`.
    headings:    optional clause_type -> heading overrides
    definitions: optional extra defined terms, e.g. {"Confidential Information": "means ..."}
    Never raises for content problems; they are reported in warnings.
    """
    title = " ".join((title or "").split())
    if not title:
        raise ValueError("title is required")
    headings = headings or {}
    warnings: list[str] = []

    # 1. Preamble (defines the Agreement and the parties' short names).
    when = format_date(deal.effective_date) if deal.effective_date else "[Effective Date]"
    if not deal.effective_date:
        warnings.append("No effective date given; '[Effective Date]' left in the preamble.")
    preamble = (
        f'This {title} (the "Agreement") is made on {when} between:\n'
        f"{_party_line(1, deal.party_a.name, deal.party_a.description, deal.party_a.short_name)}; and\n"
        f"{_party_line(2, deal.party_b.name, deal.party_b.description, deal.party_b.short_name)}."
    )

    # 2. Definitions: effective date (from facts) + caller-supplied terms.
    defs: dict[str, str] = {}
    if deal.effective_date:
        defs["Effective Date"] = f"means {format_date(deal.effective_date)}."
    for term, meaning in (definitions or {}).items():
        term, meaning = " ".join(str(term).split()), " ".join(str(meaning).split())
        if not term or not meaning:
            warnings.append(f"Ignored an empty definition: {term!r}")
            continue
        if term in defs:
            warnings.append(f'Definition of "{term}" supplied twice; the first was kept.')
            continue
        defs[term] = meaning
    definition_list = [Definition(term=t, meaning=m) for t, m in sorted(defs.items())]

    # 3. Number the clauses, dropping duplicate clause types.
    first_number = 2 if definition_list else 1
    numbered: list[tuple[int, AdaptedClause]] = []
    seen_types: set[str] = set()
    for clause in clauses:
        if clause.clause_type in seen_types:
            warnings.append(
                f"Duplicate clause type '{clause.clause_type}' ({clause.clause_id}) was left out."
            )
            continue
        seen_types.add(clause.clause_type)
        numbered.append((first_number + len(numbered), clause))
    if not numbered:
        warnings.append("The draft has no clauses.")

    ref_numbers = {c.clause_type: n for n, c in numbered}
    if definition_list:
        ref_numbers[DEFINITIONS_TYPE] = 1

    def resolve_refs(text: str, where: str) -> str:
        def sub(m: re.Match) -> str:
            target = m.group(1)
            if target in ref_numbers:
                return f"Clause {ref_numbers[target]}"
            warnings.append(f"{where}: reference to '{target}' has no matching clause.")
            return f"[UNRESOLVED REFERENCE: {target}]"
        text = XREF_RE.sub(sub, text)
        for leftover in ANY_TOKEN_RE.findall(text):
            warnings.append(f"{where}: unrecognised token {leftover} left in text.")
        return text

    # 4. Build each clause.
    draft_clauses: list[DraftClause] = []
    for number, clause in numbered:
        where = f"Clause {number} ({clause.clause_type})"
        body = resolve_refs(clause.content, where)
        paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", body) if p.strip()]
        cites = resolve_citations(clause.statute_refs)
        clause_warnings = list(clause.warnings)
        if cites.unresolved:
            clause_warnings.append(
                f"Unknown statute code(s) {cites.unresolved} - no citation shown; needs a lawyer."
            )
        draft_clauses.append(DraftClause(
            number=number,
            heading=headings.get(clause.clause_type) or default_heading(clause.clause_type),
            clause_id=clause.clause_id,
            clause_type=clause.clause_type,
            version=clause.version,
            verification_status=clause.verification_status,
            paragraphs=paragraphs or [""],
            citations=cites.citations,
            unresolved_citations=cites.unresolved,
            adaptation_status=clause.status,
            edits_applied=clause.edits_applied,
            unresolved_placeholders=clause.unresolved_placeholders,
            warnings=clause_warnings,
        ))

    # 5. Flag defined terms that the contract never uses.
    full_text = "\n".join(p for c in draft_clauses for p in c.paragraphs)
    for d in definition_list:
        if d.term != "Effective Date" and not _uses_term(full_text, d.term):
            warnings.append(f'Defined term "{d.term}" is not used in any clause.')

    return DraftDocument(
        title=title,
        contract_type=deal.contract_type,
        preamble=preamble,
        definitions=definition_list,
        definitions_number=1 if definition_list else None,
        clauses=draft_clauses,
        warnings=warnings,
    )


def _render_text(draft: DraftDocument, *, draft_label_for: set[UUID], banner: str | None,
                 label: str) -> str:
    """Plain-text rendering. Internal: call app.drafting.guard.render_for instead."""
    lines: list[str] = [draft.title.upper(), ""]
    if banner:
        lines += [banner, ""]
    lines += [draft.preamble, ""]

    if draft.definitions:
        lines += [f"{draft.definitions_number}. DEFINITIONS",
                  f"{draft.definitions_number}.1 In this Agreement:"]
        for d in draft.definitions:
            lines.append(f'    "{d.term}" {d.meaning}')
        lines.append("")

    for c in draft.clauses:
        heading = f"{c.number}. {c.heading.upper()}"
        if c.clause_id in draft_label_for:
            heading += f" {label}"
        lines.append(heading)
        if len(c.paragraphs) == 1:
            lines.append(c.paragraphs[0])
        else:
            lines += [f"{c.number}.{i} {p}" for i, p in enumerate(c.paragraphs, 1)]
        if c.citations:
            lines.append("    Statutory reference: " + "; ".join(x.text for x in c.citations))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
