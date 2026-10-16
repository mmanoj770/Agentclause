"""
D3: Runner script — embeds all clauses that don't have a vector yet.

Run from the backend/ folder:
    python -m app.clauses.embed_runner

Safe to re-run: skips already-embedded clauses automatically.
"""

from app.db import pool
from app.clauses.embedder import embed_all_pending


def main() -> None:
    print("Opening DB connection...")
    pool.open()

    try:
        with pool.connection() as conn:
            print("Checking for unembedded clauses...")
            count = embed_all_pending(conn)
            conn.commit()
    finally:
        pool.close()

    if count > 0:
        print(f"\nDone — {count} clause(s) embedded successfully.")
    else:
        print("\nDone — nothing to embed.")


if __name__ == "__main__":
    main()
