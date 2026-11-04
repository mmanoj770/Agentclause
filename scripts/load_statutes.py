#!/usr/bin/env python3
"""Load seed statutes into public.statutes (R8 #3).

Idempotent: skips rows that already exist based on (act, section, effective_from).
Always inserts as 'staging' (unverified); NEVER sets 'verified'.
Dry-run by default; pass --apply to execute writes.

Usage:
    python scripts/load_statutes.py [--apply] [--file path/to/seed_statutes.json]
"""
import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

# Add backend directory to sys.path so app modules are available
backend_dir = Path(__file__).resolve().parents[1] / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.db import pool
from app.statutes.normalizer import normalise_act_name, normalise_section_number

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("load_statutes")

DEFAULT_SEED = backend_dir / "app" / "rules" / "config" / "seed_statutes.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_statutes(seed_path: Path, apply: bool = False) -> None:
    if not seed_path.is_file():
        log.error("Seed file not found: %s", seed_path)
        sys.exit(1)

    file_hash = sha256_of(seed_path)
    log.info("Reading seed file: %s (SHA-256: %s)", seed_path, file_hash)

    data = json.loads(seed_path.read_text())
    if not isinstance(data, list):
        log.error("Seed file must contain a JSON array of statute entries.")
        sys.exit(1)

    log.info("Found %d statute entries to process. Mode: %s", len(data), "APPLY" if apply else "DRY-RUN")

    pool.open()
    try:
        with pool.connection() as conn:
            # Verify public.statutes exists
            exists = conn.execute("select to_regclass('public.statutes') is not null as ok").fetchone()
            if not exists or not exists["ok"]:
                log.error("Table public.statutes does not exist. Apply migration 21 first.")
                sys.exit(1)

            inserted = 0
            skipped = 0

            for entry in data:
                act = normalise_act_name(entry["act"])
                section = normalise_section_number(entry["section"])
                effective_from = entry["effective_from"]
                effective_to = entry.get("effective_to")
                heading = entry.get("heading")
                statute_text = entry["statute_text"]
                source_url = entry.get("source_url")

                # Check if row exists
                existing = conn.execute(
                    "select id, status from public.statutes where act = %s and section = %s and effective_from = %s",
                    (act, section, effective_from)
                ).fetchone()

                if existing:
                    skipped += 1
                    log.info("SKIP (exists): %s s. %s (effective: %s, status: %s)",
                             act, section, effective_from, existing["status"])
                    continue

                if apply:
                    conn.execute(
                        """
                        insert into public.statutes
                            (act, section, heading, statute_text, source_url, effective_from, effective_to, status)
                        values
                            (%s, %s, %s, %s, %s, %s, %s, 'staging')
                        """,
                        (act, section, heading, statute_text, source_url, effective_from, effective_to)
                    )
                inserted += 1
                log.info("INSERT (%s): %s s. %s (effective: %s)",
                         "APPLIED" if apply else "WOULD INSERT", act, section, effective_from)

            if apply:
                conn.commit()
                log.info("SUCCESS: Inserted %d rows, skipped %d existing rows.", inserted, skipped)
            else:
                conn.rollback()
                log.info("DRY-RUN FINISHED: Would insert %d rows, skipped %d existing rows. No changes committed.",
                         inserted, skipped)
    finally:
        pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load seed statutes into public.statutes")
    parser.add_argument("--apply", action="store_true", help="Execute the insert and commit to database")
    parser.add_argument("--file", type=Path, default=DEFAULT_SEED, help="Path to seed JSON file")
    args = parser.parse_args()

    load_statutes(args.file, apply=args.apply)
