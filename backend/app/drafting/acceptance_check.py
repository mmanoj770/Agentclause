"""
Acceptance check for the lead's D3-D5 "done when" criteria, run against your local
database and the REAL Gemini API.

Run from the backend/ folder (after `supabase migration up`):
    python -m app.drafting.acceptance_check

What it checks
  D3  seeding and embedding twice creates no duplicates; >= 10 placeholder clauses
      are embedded with the current model; the second embedding run embeds nothing.
  D4  the query "confidentiality" for an NDA returns the confidentiality clause first.
  D5  three sample deals produce the expected clauses, with no leftover placeholders,
      and the diff against the source shows only fact substitutions.

It seeds the placeholder clauses (staging only) and stores their embeddings; it changes
nothing else. Exit code 0 = every check passed, 1 = something failed.
"""

from __future__ import annotations

import sys

from app.clauses.embedder import current_model, embed_all_pending
from app.clauses.seed_runner import SEED_FILE, seed_file
from app.drafting.adaptation import adapt_clause
from app.drafting.retrieval import retrieve_clauses
from app.drafting.sample_deals import SAMPLE_DEALS, check_adapted

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def check_embedding(conn) -> None:
    print("\n== D3: embedding ==")
    inserted, skipped = seed_file(conn, SEED_FILE)
    conn.commit()
    print(f"  seed run 1: {inserted} inserted, {skipped} already present")
    first = embed_all_pending(conn)
    conn.commit()
    print(f"  embed run 1: {first.summary()}")

    count_before = conn.execute("SELECT count(*) AS n FROM clauses").fetchone()["n"]
    inserted2, _ = seed_file(conn, SEED_FILE)
    conn.commit()
    second = embed_all_pending(conn)
    conn.commit()
    print(f"  embed run 2: {second.summary()}")
    count_after = conn.execute("SELECT count(*) AS n FROM clauses").fetchone()["n"]
    dupes = conn.execute(
        """SELECT count(*) AS n FROM (
               SELECT 1 FROM clauses GROUP BY clause_type, title, version HAVING count(*) > 1
           ) d"""
    ).fetchone()["n"]

    record("Second run creates no duplicate clauses",
           inserted2 == 0 and count_before == count_after and dupes == 0,
           f"rows {count_before} -> {count_after}, duplicate groups {dupes}")
    record("Second run embeds nothing (idempotent)",
           second.embedded == 0 and not second.failed, second.summary())
    embedded = conn.execute(
        """SELECT count(*) AS n FROM clauses
            WHERE verification_status = 'staging' AND embedding IS NOT NULL
              AND embedding_model = %s AND embedded_version = version""",
        (current_model(),),
    ).fetchone()["n"]
    record("At least 10 placeholder clauses embedded", embedded >= 10,
           f"{embedded} embedded with {current_model()}")
    if first.failed or second.failed:
        for clause_id, reason in first.failed + second.failed:
            print(f"    failed {clause_id}: {reason}")


def check_retrieval(conn) -> None:
    print("\n== D4: retrieval ==")
    res = retrieve_clauses(conn, None, "nda", "confidentiality", k=5)
    for w in res.warnings:
        print(f"  warning: {w}")
    for c in res.clauses:
        score = f"{c.score:.3f}" if c.score is not None else "  -  "
        print(f"  {score}  {c.clause_type:<24} v{c.version} {c.tier:<8} {c.statute_refs}")
    top = res.clauses[0].clause_type if res.clauses else None
    record('"confidentiality" for an NDA returns the confidentiality clause first',
           top == "confidentiality" and res.clauses[0].score is not None,
           f"top result: {top}")


def check_adaptation(conn) -> None:
    print("\n== D5: adaptation (real Gemini) ==")
    for sample in SAMPLE_DEALS:
        print(f"\n  Deal: {sample.name}")
        problems_for_deal = []
        for clause_type in sample.expected:
            found = retrieve_clauses(conn, clause_type, sample.deal.contract_type, k=1).clauses
            if not found:
                problems_for_deal.append(f"{clause_type}: no clause found")
                continue
            adapted = adapt_clause(found[0], sample.deal)
            print(f"    {clause_type} (clause {adapted.clause_id}, v{adapted.version}):")
            print(f"      {adapted.content}")
            for change in adapted.diff:
                print(f"      diff: '{change.removed}' -> '{change.inserted}'  [fact: {change.fact}]")
            for rej in adapted.edits_rejected:
                print(f"      rejected edit: {rej.edit} - {rej.reason}")
            problems_for_deal += [f"{clause_type}: {p}" for p in check_adapted(sample, clause_type, adapted)]
        record(f"Deal '{sample.name}' produces correct clauses with fact-only diffs",
               not problems_for_deal, "; ".join(problems_for_deal))


def main() -> int:
    from app.db import pool

    pool.open()
    try:
        with pool.connection() as conn:
            check_embedding(conn)
            check_retrieval(conn)
            check_adaptation(conn)
    finally:
        pool.close()

    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
