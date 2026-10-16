"""
D3: Runner script - embeds every clause that is new or out of date.

Run from the backend/ folder:
    python -m app.clauses.embed_runner

Safe to re-run: up-to-date clauses are skipped, and a clause is re-embedded when its
text, version or the embedding model changes. Prints embedded / skipped / failed counts.
Exits with code 1 if any clause failed, so failures are never silent.
"""

import sys

from app.clauses.embedder import embed_all_pending
from app.db import pool


def main() -> int:
    print("Opening DB connection...")
    pool.open()
    try:
        with pool.connection() as conn:
            result = embed_all_pending(conn)
            conn.commit()
    finally:
        pool.close()

    print(f"\nDone - {result.summary()}.")
    if result.failed:
        print("Failed clauses (fix the cause, then re-run; successful ones are kept):")
        for clause_id, reason in result.failed:
            print(f"  - {clause_id}: {reason}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
