from uuid import uuid4

import pytest

from app.agents.conversational.contract import CitationSource
from app.agents.conversational.embeddings import HashEmbedder
from app.agents.conversational.ingest import ingest_contract
from app.agents.conversational.retrieval import DocumentIndex

SAMPLE = """1. Term
1.1 This Agreement remains in force for two (2) years from the effective date.

2. Governing Law
2.1 This Agreement is governed by the laws of India.

3. Payment
3.1 Invoices are payable within forty five days of receipt.
"""

OTHER = """1. Termination
1.1 Either party may terminate this Agreement on thirty days written notice.
"""


def build_index():
    index = DocumentIndex(HashEmbedder())
    doc_a, doc_b = uuid4(), uuid4()
    index.index_document(doc_a, ingest_contract(doc_a, "a.txt", SAMPLE.encode()))
    index.index_document(doc_b, ingest_contract(doc_b, "b.txt", OTHER.encode()))
    return index, doc_a, doc_b


def test_relevant_clause_ranks_first():
    index, doc_a, _ = build_index()
    results = index.search(doc_a, "governing law of India")
    assert results[0].chunk.clause_number == "2.1"


def test_search_never_returns_other_documents():
    index, doc_a, doc_b = build_index()
    results = index.search(doc_a, "terminate on thirty days written notice")
    assert all(r.chunk.document_id == doc_a for r in results)
    results_b = index.search(doc_b, "governing law of India")
    assert all(r.chunk.document_id == doc_b for r in results_b)


def test_unknown_document_returns_nothing():
    index, _, _ = build_index()
    assert index.search(uuid4(), "anything") == []


def test_lawyer_note_is_retrievable():
    index = DocumentIndex(HashEmbedder())
    doc = uuid4()
    chunks = ingest_contract(doc, "a.txt", SAMPLE.encode())
    index.index_document(doc, chunks, notes=["Lawyer confirms the payment period complies with MSMED."])
    results = index.search(doc, "does payment period comply with MSMED")
    assert results[0].chunk.source == CitationSource.LAWYER_NOTE


def test_empty_index_rejected():
    index = DocumentIndex(HashEmbedder())
    with pytest.raises(ValueError):
        index.index_document(uuid4(), [])


def test_mismatched_document_rejected():
    index = DocumentIndex(HashEmbedder())
    doc, other = uuid4(), uuid4()
    chunks = ingest_contract(other, "a.txt", SAMPLE.encode())
    with pytest.raises(ValueError):
        index.index_document(doc, chunks)

def test_remove_document_forgets_it():
    index, doc_a, doc_b = build_index()
    index.remove_document(doc_a)
    assert not index.has_document(doc_a)
    assert index.search(doc_a, "governing law") == []
    assert index.has_document(doc_b)
    index.remove_document(doc_a)