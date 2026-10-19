import argparse
import json
import statistics
from pathlib import Path
from uuid import uuid4

from app.agents.conversational.embeddings import SentenceTransformerEmbedder
from app.agents.conversational.gates import clamp_score
from app.agents.conversational.ingest import ingest_contract
from app.agents.conversational.retrieval import DocumentIndex


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract")
    parser.add_argument("--data", default="tests/agents/conversational/data/retrieval_set.json")
    parser.add_argument("--k", type=int, default=4)
    args = parser.parse_args()

    path = Path(args.contract)
    items = json.loads(Path(args.data).read_text(encoding="utf-8"))
    doc_id = uuid4()
    index = DocumentIndex(SentenceTransformerEmbedder())
    index.index_document(doc_id, ingest_contract(doc_id, path.name, path.read_bytes()))

    answerable, unanswerable = [], []
    hits = 0
    total_answerable = 0

    print(f"{'score':>6}  {'hit':3}  {'kind':12} top clause / question")
    for item in items:
        results = index.search(doc_id, item["q"], k=args.k)
        top = results[0]
        score = clamp_score(top.score)
        label = "answerable" if item["answerable"] else "unanswerable"
        hit = ""
        if item["answerable"]:
            total_answerable += 1
            found = any(r.chunk.clause_number in item["clauses"] for r in results)
            hits += found
            hit = "yes" if found else "NO"
            answerable.append((score, found, item["q"]))
        else:
            unanswerable.append((score, item["q"]))
        print(f"{score:6.2f}  {hit:3}  {label:12} [{top.chunk.clause_number}] {item['q'][:55]}")

    print(f"\nretrieval hit@{args.k}: {hits}/{total_answerable}")
    good_scores = [s for s, found, _ in answerable if found]
    un_scores = [s for s, _ in unanswerable]
    print(f"answerable top scores (correctly retrieved): min {min(good_scores):.2f}  median {statistics.median(good_scores):.2f}  max {max(good_scores):.2f}")
    print(f"unanswerable top scores: min {min(un_scores):.2f}  median {statistics.median(un_scores):.2f}  max {max(un_scores):.2f}")

    suggested = max(0.05, round(min(good_scores) - 0.03, 2))
    refused_un = sum(1 for s in un_scores if s < suggested)
    refused_ans = sum(1 for s, _, _ in answerable if s < suggested)
    print(f"\nsuggested threshold: {suggested:.2f}  (just below the weakest correct retrieval)")
    print(f"  refuses {refused_un}/{len(un_scores)} unanswerable questions")
    print(f"  wrongly refuses {refused_ans}/{len(answerable)} answerable questions")

    if min(un_scores) >= suggested:
        print("\nNOTE: no unanswerable question scored below the threshold.")
        print("The gate cannot separate them on this model; the answerable=false check in generation (C4) and NLI (C7) must catch these.")


if __name__ == "__main__":
    main()