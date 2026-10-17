from io import BytesIO
from uuid import uuid4

import pytest

from app.agents.conversational.ingest import ingest_contract

DOC = uuid4()

SAMPLE = """NON-DISCLOSURE AGREEMENT
This Agreement is made between Alpha Pvt Ltd and Beta LLP.
1 January 2026 is the effective date.

1. Definitions
1.1 Confidential Information means all non-public information disclosed by one party to the other.
1.2 Purpose means evaluating a possible business relationship.

2. Term
2.1 This Agreement remains in force for two (2) years from the effective date.

3. Governing Law
3.1 This Agreement is governed by the laws of India.
"""


def test_splits_numbered_clauses():
    chunks = ingest_contract(DOC, "nda.txt", SAMPLE.encode())
    assert [c.clause_number for c in chunks] == [None, "1.1", "1.2", "2.1", "3.1"]
    assert [c.heading for c in chunks] == [
        "Preamble",
        "Definitions",
        "Definitions",
        "Term",
        "Governing Law",
    ]


def test_date_line_is_not_a_clause():
    chunks = ingest_contract(DOC, "nda.txt", SAMPLE.encode())
    assert "1 January 2026" in chunks[0].text


def test_chunk_ids_unique_and_ordered():
    chunks = ingest_contract(DOC, "nda.txt", SAMPLE.encode())
    ids = [c.chunk_id for c in chunks]
    assert len(set(ids)) == len(ids)
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_docx_roundtrip():
    from docx import Document

    doc = Document()
    for line in SAMPLE.splitlines():
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    chunks = ingest_contract(DOC, "nda.docx", buf.getvalue())
    assert [c.clause_number for c in chunks] == [None, "1.1", "1.2", "2.1", "3.1"]


def test_unnumbered_text_falls_back_to_paragraphs():
    text = "First paragraph about payment.\n\nSecond paragraph about term."
    chunks = ingest_contract(DOC, "plain.txt", text.encode())
    assert len(chunks) == 2
    assert all(c.clause_number is None for c in chunks)


def test_unsupported_type_rejected():
    with pytest.raises(ValueError):
        ingest_contract(DOC, "contract.png", b"x")


def test_empty_document_rejected():
    with pytest.raises(ValueError):
        ingest_contract(DOC, "empty.txt", b"   ")