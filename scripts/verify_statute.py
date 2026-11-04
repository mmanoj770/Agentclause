#!/usr/bin/env python3
"""Flip a statute's verification_status to 'verified' (or revert to 'staging') with audit logging (R8 #3).

Run ONLY after an advocate's written confirmation. Executes in a single transaction.

Usage:
    python scripts/verify_statute.py --act "Indian Contract Act, 1872" --section "27" \\
        --by "advocate@example.com" --ref "ADV-CONFIRM-2026-11-04" [--revert]
"""
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parents[1] / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.audit import write_audit
from app.db import pool
from app.statutes.normalizer import normalise_act_name, normalise_section_number

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("verify_statute")


def verify_statute(act: str, section: str, verified_by: str, verification_ref: str, revert: bool = False):
    norm_act = normalise_act_name(act)
    norm_sec = normalise_section_number(section)

    pool.open()
    try:
        with pool.connection() as conn:
            with conn.transaction():
                row = conn.execute(
                    "select id, act, section, status, verified_by, verification_ref from public.statutes "
                    "where act = %s and section = %s for update",
                    (norm_act, norm_sec)
                ).fetchone()

                if not row:
                    log.error("Statute not found: %s s. %s", norm_act, norm_sec)
                    sys.exit(1)

                statute_id = row["id"]
                current_status = row["status"]

                if not revert:
                    if current_status == "verified":
                        log.info("Already verified by %s (ref: %s)", row["verified_by"], row["verification_ref"])
                        return
                    new_status = "verified"
                    now = datetime.now(timezone.utc)
                    conn.execute(
                        """
                        update public.statutes
                        set status = 'verified', verified_by = %s, verified_at = %s, verification_ref = %s
                        where id = %s
                        """,
                        (verified_by, now, verification_ref, statute_id)
                    )
                    action = "statute_verified"
                    details = {
                        "statute_id": str(statute_id),
                        "act": norm_act,
                        "section": norm_sec,
                        "verified_by": verified_by,
                        "verification_ref": verification_ref,
                    }
                else:
                    if current_status == "staging":
                        log.info("Already in staging (unverified)")
                        return
                    new_status = "staging"
                    conn.execute(
                        """
                        update public.statutes
                        set status = 'staging', verified_by = null, verified_at = null, verification_ref = null
                        where id = %s
                        """,
                        (statute_id,)
                    )
                    action = "statute_unverified"
                    details = {
                        "statute_id": str(statute_id),
                        "act": norm_act,
                        "section": norm_sec,
                        "reverted_by": verified_by,
                        "reason": verification_ref,
                    }

                write_audit(
                    conn,
                    document_id=None,
                    actor_id=None,
                    actor_role="system",
                    action=action,
                    details=details
                )
                log.info("SUCCESS: Updated %s s. %s to status '%s' (action: %s)",
                         norm_act, norm_sec, new_status, action)
    finally:
        pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify or unverify a statute row in public.statutes")
    parser.add_argument("--act", required=True, help="Act name or alias (e.g. 'ICA', 'Indian Contract Act, 1872')")
    parser.add_argument("--section", required=True, help="Section number (e.g. '27', '27(1)')")
    parser.add_argument("--by", required=True, help="Advocate email or name")
    parser.add_argument("--ref", required=True, help="Advocate confirmation reference or document ID")
    parser.add_argument("--revert", action="store_true", help="Revert from verified back to staging")
    args = parser.parse_args()

    verify_statute(args.act, args.section, args.by, args.ref, revert=args.revert)
