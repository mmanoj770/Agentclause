"""
Load the placeholder (staging) clauses into the local database.

Run from the backend/ folder:
    python -m app.clauses.seed_runner

Safe to re-run: a clause whose (clause_type, title, version) already exists is skipped.
After seeding, run `python -m app.clauses.embed_runner` to embed the new clauses.
"""

import json
import sys
from pathlib import Path

from app.clauses.loader import load_clause
from app.db import pool

SEED_FILE = Path(__file__).parent / "seeds" / "placeholder_clauses.json"


def main() -> int:
    items = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    inserted = skipped = 0
    pool.open()
    try:
        with pool.connection() as conn:
            for item in items:
                exists = conn.execute(
                    "SELECT 1 FROM clauses WHERE clause_type = %s AND title = %s AND version = %s",
                    (item.get("clause_type"), item.get("title"), item.get("version", 1)),
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
                load_clause(conn, item)
                inserted += 1
            conn.commit()
    finally:
        pool.close()
    print(f"Done - {inserted} clause(s) inserted, {skipped} already present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
