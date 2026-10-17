import sys
from pathlib import Path
from uuid import uuid4

from app.agents.conversational.embeddings import SentenceTransformerEmbedder
from app.agents.conversational.generation import generate_answer
from app.agents.conversational.ingest import ingest_contract
from app.agents.conversational.llm import get_llm_client
from app.agents.conversational.retrieval import DocumentIndex

path = Path(sys.argv[1])
questions = sys.argv[2:]

doc_id = uuid4()
index = DocumentIndex(SentenceTransformerEmbedder())
index.index_document(doc_id, ingest_contract(doc_id, path.name, path.read_bytes()))
llm = get_llm_client()
for q in questions:
    print(f"\nQ: {q}")
    retrieved = index.search(doc_id, q)
    result = generate_answer(q, retrieved, llm)
    if result is None:
        print("  -> no grounded answer")
        continue
    for claim in result.claims:
        print(f"  - {claim.text}")
    for c in result.citations:
        print(f"    cites [{c.clause_number}] {c.heading}")