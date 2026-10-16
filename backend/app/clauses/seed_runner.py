"""
Load placeholder (staging) clauses into the local database.

Run from the backend/ folder:
    python -m app.clauses.seed_runner                 # the placeholder file
    python -m app.clauses.seed_runner path/to/file.json

Safe to re-run: a clause whose (clause_type, title, version) already exists is skipped,
so running it twice creates no duplicates.
After seeding, run `python -m app.clauses.embed_runner` to embed the new clauses.
"""

import json
import sys
from pathlib import Path

from app.clauses.loader import load_clause

SEED_FILE = Path(__file__).parent / "seeds" / "placeholder_clauses.json"


def seed_file(conn, path: Path = SEED_FILE) -> tuple[int, int]:
    """Insert clauses from a JSON file that are not already present. Returns (inserted, skipped)."""
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError(f"{path} must contain a JSON list of clauses")
    inserted = skipped = 0
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
    return inserted, skipped


def main() -> int:
    from app.db import pool

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SEED_FILE
    pool.open()
    try:
        with pool.connection() as conn:
            inserted, skipped = seed_file(conn, path)
            conn.commit()
    finally:
        pool.close()
    print(f"Done - {inserted} clause(s) inserted, {skipped} already present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
