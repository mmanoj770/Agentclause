import sys
from pathlib import Path
from uuid import uuid4

from app.agents.conversational.embeddings import SentenceTransformerEmbedder
from app.agents.conversational.ingest import ingest_contract
from app.agents.conversational.retrieval import DocumentIndex

path = Path(sys.argv[1])
questions = sys.argv[2:] or ["How long does this agreement last?"]

doc_id = uuid4()
chunks = ingest_contract(doc_id, path.name, path.read_bytes())
print(f"{len(chunks)} chunks found\n")
for c in chunks:
    print(f"  [{c.clause_number}] {c.heading} | {c.text[:50]!r}")

index = DocumentIndex(SentenceTransformerEmbedder())
index.index_document(doc_id, chunks)

for q in questions:
    print(f"\nQ: {q}")
    for r in index.search(doc_id, q):
        print(f"  {r.score:.2f}  [{r.chunk.clause_number}] {r.chunk.heading}")