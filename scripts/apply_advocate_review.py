#!/usr/bin/env python3
"""Apply an advocate's completed review CSV, flipping verification_status only for rows marked verified,
and recording a detailed entry in docs/rules_verification_changelog.md.

Usage:
    python3 scripts/apply_advocate_review.py [path/to/completed_review.csv]

DO NOT RUN THIS SCRIPT UNTIL AN ADVOCATE HAS ACTUALLY REVIEWED AND SIGNED OFF ON THE CSV.
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "backend" / "app" / "rules" / "rules"
CONFIG_DIR = ROOT / "backend" / "app" / "rules" / "config"
DOCS_DIR = ROOT / "docs"
CHANGELOG_PATH = DOCS_DIR / "rules_verification_changelog.md"


def is_verified(row: dict) -> bool:
    v = row.get("verified", "").strip().lower()
    combined = row.get("verified / corrected quote / notes", "").strip().lower()
    return v in ("yes", "verified", "true", "1", "pass") or ("verified" in combined and "unverified" not in combined)


def apply_review(csv_path: Path):
    if not csv_path.exists():
        print(f"Error: CSV file not found at {csv_path}", file=sys.stderr)
        sys.exit(1)

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    verified_rules = []
    verified_clauses = {}
    quote_corrections = {}

    for row in rows:
        cat = row.get("category", "").strip()
        ident = row.get("identifier", "").strip()
        if not is_verified(row):
            continue

        corrected_quote = row.get("corrected_quote", "").strip()
        notes = row.get("notes", "").strip() or row.get("verified / corrected quote / notes", "").strip()

        if cat == "seed_rule":
            verified_rules.append((ident, corrected_quote, notes))
        elif cat == "required_clause":
            contract_type, clause_name = ident.split(":", 1)
            verified_clauses.setdefault(contract_type, []).append((clause_name, notes))

    if not verified_rules and not verified_clauses:
        print("No verified rows found in the CSV. Nothing to apply.")
        return 0

    applied_changes = []

    # 1. Apply verified rules
    for rule_id, corrected_quote, notes in verified_rules:
        target_file = None
        for p in RULES_DIR.glob("*.json"):
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("rule_id") == rule_id:
                target_file = p
                break
        if not target_file:
            print(f"Warning: Rule file for {rule_id} not found", file=sys.stderr)
            continue

        data = json.loads(target_file.read_text(encoding="utf-8"))
        old_status = data.get("verification_status", "unverified")
        data["verification_status"] = "verified"
        if corrected_quote:
            data["basis"] = corrected_quote
        target_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        applied_changes.append(
            f"- **Rule `{rule_id}`** ({target_file.name}): `{old_status}` -> `verified`"
            + (f" (quote corrected: `{corrected_quote[:60]}...`)" if corrected_quote else "")
            + (f" | Notes: {notes}" if notes else "")
        )

    # 2. Check and apply completeness configs
    for c_id, verified_list in verified_clauses.items():
        cfg_path = CONFIG_DIR / f"{c_id}_required_clauses.json"
        if not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        required_keys = {r["clause"] for r in cfg.get("required", [])}
        verified_keys = {c[0] for c in verified_list}

        # If all required clauses for this contract type were marked verified
        if required_keys and required_keys <= verified_keys:
            old_status = cfg.get("verification_status", "unverified")
            cfg["verification_status"] = "verified"
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
            applied_changes.append(
                f"- **Completeness Config `{c_id}`** ({cfg_path.name}): `{old_status}` -> `verified` "
                f"({len(verified_keys)} clauses confirmed)"
            )

    # 3. Write Changelog Entry
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    changelog_entry = [
        f"## Verification Applied: {now_str}",
        f"Applied from: `{csv_path}`",
        "",
        "### Changes:",
    ]
    changelog_entry.extend(applied_changes)
    changelog_entry.append("\n---\n")

    if CHANGELOG_PATH.exists():
        existing = CHANGELOG_PATH.read_text(encoding="utf-8")
    else:
        existing = "# Rules Verification Changelog\n\nAudit log of advocate verifications applied to rules and configs.\n\n---\n\n"

    CHANGELOG_PATH.write_text(existing + "\n".join(changelog_entry) + "\n", encoding="utf-8")
    print(f"Applied {len(applied_changes)} verification update(s). Changelog updated at {CHANGELOG_PATH}.")
    return len(applied_changes)


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DOCS_DIR / "advocate_review_pack.csv"
    apply_review(path)
