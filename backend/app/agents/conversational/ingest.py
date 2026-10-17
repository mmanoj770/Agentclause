import re
from io import BytesIO
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from app.agents.conversational.contract import CitationSource

CLAUSE_RE = re.compile(
    r"^\s*(?:(?:clause|section|article)\s+)?(\d+(?:\.\d+)+\.?|\d+[.)])\s+(\S.*)$",
    re.IGNORECASE,
)
MAX_HEADING_LEN = 60
PAGE_NUMBER_RE = re.compile(r"^\d{1,3}$")


class ClauseChunk(BaseModel):
    chunk_id: str
    document_id: UUID
    source: CitationSource = CitationSource.DOCUMENT
    position: int
    clause_number: str | None
    heading: str | None
    text: str


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        return data.decode("utf-8", errors="ignore")
    if suffix == ".docx":
        from docx import Document

        return "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
    raise ValueError(f"unsupported file type: {suffix or 'none'}")


def _looks_like_heading(text: str) -> bool:
    return len(text) <= MAX_HEADING_LEN and not text.endswith((".", ";", ","))


def split_into_clauses(text: str) -> list[dict]:
    sections = []
    current = {"clause_number": None, "heading": "Preamble", "lines": []}
    top_headings: dict[str, str] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or PAGE_NUMBER_RE.match(line):
            continue
        match = CLAUSE_RE.match(line)
        if not match:
            current["lines"].append(line)
            continue

        number = match.group(1).rstrip(".)")
        rest = match.group(2).strip()
        parts = number.split(".")

        same_parent = (
            len(parts) > 2
            and current["clause_number"]
            and current["clause_number"].split(".")[:2] == parts[:2]
        )
        if same_parent:
            current["lines"].append(f"{number} {rest}")
            continue

        sections.append(current)
        top = parts[0]
        if len(parts) == 1 and _looks_like_heading(rest):
            heading = rest.rstrip(":").strip()
            top_headings[top] = heading
            body = []
        else:
            heading = top_headings.get(top)
            body = [rest]
        current = {"clause_number": number, "heading": heading, "lines": body}

    sections.append(current)
    return [s for s in sections if s["lines"]]


def ingest_contract(document_id: UUID, filename: str, data: bytes) -> list[ClauseChunk]:
    text = extract_text(filename, data).strip()
    if not text:
        raise ValueError("no extractable text found in document")

    sections = split_into_clauses(text)
    if all(s["clause_number"] is None for s in sections):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        sections = [
            {"clause_number": None, "heading": None, "lines": [p]} for p in paragraphs
        ]

    return [
        ClauseChunk(
            chunk_id=f"{document_id}:{i}",
            document_id=document_id,
            position=i,
            clause_number=s["clause_number"],
            heading=s["heading"],
            text="\n".join(s["lines"]),
        )
        for i, s in enumerate(sections)
    ]