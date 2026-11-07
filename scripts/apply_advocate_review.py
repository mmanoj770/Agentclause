#!/usr/bin/env python3
"""Apply an advocate's completed review CSV with strict safety guards.

Guards:
- Refuses rows where corrected quote differs from staged quote without a new verification_ref.
- Requires advocate name/ID and verification date for every verified row.
- Applies changes atomically to BOTH rule files and seed_statutes.json (if either fails, neither is written).
- Supports --dry-run (default) and --apply.
- Changelog records operator, advocate, date, old/new quote hashes, and ref.

Usage:
    python3 scripts/apply_advocate_review.py [--apply | --dry-run] [path/to/completed_review.csv]

DO NOT RUN THIS SCRIPT WITH --apply ON REAL REPO DATA UNTIL FORMAL ADVOCATE SIGN-OFF.
"""
import argparse
import csv
import getpass
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "backend" / "app" / "rules" / "rules"
CONFIG_DIR = ROOT / "backend" / "app" / "rules" / "config"
DOCS_DIR = ROOT / "docs"
CHANGELOG_PATH = DOCS_DIR / "rules_verification_changelog.md"


class ReviewRefusalError(Exception):
    """Raised when an advocate review row fails safety or evidence validation."""


def short_hash(text: str) -> str:
    if not text:
        return "none"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def is_verified(row: dict) -> bool:
    v = row.get("verified", "").strip().lower()
    combined = row.get("verified / corrected quote / notes", "").strip().lower()
    return v in ("yes", "verified", "true", "1", "pass") or ("verified" in combined and "unverified" not in combined)


def apply_review(csv_path: Path, apply_changes: bool = False) -> int:
    if not csv_path.exists():
        print(f"Error: CSV file not found at {csv_path}", file=sys.stderr)
        sys.exit(1)

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    verified_rules = []
    verified_statutes = []
    verified_clauses = {}

    # 1. Validation & Guard Checks
    for idx, row in enumerate(rows, start=2):
        ident = row.get("identifier", "").strip()
        cat = row.get("category", "").strip()
        if not is_verified(row):
            continue

        advocate = (row.get("advocate_name", "").strip()
                    or row.get("advocate_id", "").strip())
        if not advocate:
            raise ReviewRefusalError(
                f"Row {idx} ({ident}): verified row is missing required advocate_name / advocate_id"
            )

        v_date = row.get("verification_date", "").strip()
        if not v_date:
            raise ReviewRefusalError(
                f"Row {idx} ({ident}): verified row is missing required verification_date"
            )

        staged_quote = row.get("staged_quote_or_description", "").strip()
        corrected_quote = row.get("corrected_quote", "").strip()
        v_ref = row.get("verification_ref", "").strip()

        # If quote changed, require authoritative India Code / statutory reference URL
        if corrected_quote and corrected_quote != staged_quote:
            if not v_ref or not (v_ref.startswith("http://") or v_ref.startswith("https://")):
                raise ReviewRefusalError(
                    f"Row {idx} ({ident}): corrected quote differs from staged quote but "
                    f"verification_ref (India Code URL) is missing or invalid: {v_ref!r}"
                )

        notes = row.get("notes", "").strip() or row.get("verified / corrected quote / notes", "").strip()
        act = row.get("statute_or_context", "").strip()
        sec = row.get("section_or_clause", "").strip()

        if cat == "seed_rule":
            verified_rules.append({
                "rule_id": ident,
                "act": act,
                "section": sec,
                "advocate": advocate,
                "date": v_date,
                "staged_quote": staged_quote,
                "corrected_quote": corrected_quote,
                "verification_ref": v_ref,
                "notes": notes,
            })
        elif cat == "statute":
            verified_statutes.append({
                "identifier": ident,
                "act": act,
                "section": sec,
                "advocate": advocate,
                "date": v_date,
                "staged_quote": staged_quote,
                "corrected_quote": corrected_quote,
                "verification_ref": v_ref,
                "notes": notes,
            })
        elif cat == "required_clause":
            if ":" in ident:
                c_type, clause_name = ident.split(":", 1)
            else:
                c_type, clause_name = row.get("contract_type_or_applies_to", "").strip(), sec
            verified_clauses.setdefault(c_type, []).append((clause_name, advocate, v_date, notes))

    if not verified_rules and not verified_statutes and not verified_clauses:
        print("No verified rows found in the CSV. Nothing to apply.")
        return 0

    # 2. Prepare Atomic File Modifications in Memory
    staged_file_writes: dict[Path, str] = {}
    changelog_entries: list[str] = []
    operator = os.environ.get("USER") or getpass.getuser() or "operator"

    # A. Update Rule JSONs
    for r in verified_rules:
        rule_id = r["rule_id"]
        target_file = None
        for p in RULES_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("rule_id") == rule_id:
                target_file = p
                break
        if not target_file:
            raise ReviewRefusalError(f"Rule file for {rule_id} not found in {RULES_DIR}")

        data = json.loads(target_file.read_text(encoding="utf-8"))
        old_status = data.get("verification_status", "unverified")
        old_quote = data.get("basis", "")
        new_quote = r["corrected_quote"] if r["corrected_quote"] else old_quote

        data["verification_status"] = "verified"
        if r["corrected_quote"]:
            data["basis"] = r["corrected_quote"]

        staged_file_writes[target_file] = json.dumps(data, indent=2) + "\n"

        ref_str = r["verification_ref"] or "staged India Code ref"
        changelog_entries.append(
            f"- **Rule `{rule_id}`** ({target_file.name}): `{old_status}` -> `verified` | "
            f"Advocate: `{r['advocate']}` | Date: `{r['date']}` | Operator: `{operator}` | "
            f"Quote Hash: `{short_hash(old_quote)}` -> `{short_hash(new_quote)}` | Ref: {ref_str}"
        )

    # B. Update seed_statutes.json Atomically
    seed_statutes_path = CONFIG_DIR / "seed_statutes.json"
    if seed_statutes_path.exists():
        seeds = json.loads(seed_statutes_path.read_text(encoding="utf-8"))
        seeds_modified = False
        all_statute_entries = verified_rules + verified_statutes
        for stat_update in all_statute_entries:
            act = stat_update["act"]
            sec = stat_update["section"]
            for s in seeds:
                if s["act"].strip().lower() == act.lower() and s["section"].strip().lower() == sec.lower():
                    s["status"] = "verified"
                    s["verified_by"] = stat_update["advocate"]
                    s["verified_at"] = stat_update["date"]
                    if stat_update["corrected_quote"]:
                        s["statute_text"] = stat_update["corrected_quote"]
                    if stat_update["verification_ref"]:
                        s["source_url"] = stat_update["verification_ref"]
                    seeds_modified = True
                    break
        if seeds_modified:
            staged_file_writes[seed_statutes_path] = json.dumps(seeds, indent=2) + "\n"

    # C. Update Required Clause Completeness Configs
    for c_id, verified_list in verified_clauses.items():
        cfg_path = CONFIG_DIR / f"{c_id}_required_clauses.json"
        if not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        required_keys = {item["clause"] for item in cfg.get("required", [])}
        verified_keys = {item[0] for item in verified_list}

        if required_keys and required_keys <= verified_keys:
            old_status = cfg.get("verification_status", "unverified")
            cfg["verification_status"] = "verified"
            staged_file_writes[cfg_path] = json.dumps(cfg, indent=2) + "\n"
            sample_advocate = verified_list[0][1]
            sample_date = verified_list[0][2]
            changelog_entries.append(
                f"- **Completeness Config `{c_id}`** ({cfg_path.name}): `{old_status}` -> `verified` "
                f"({len(verified_keys)} clauses confirmed) | Advocate: `{sample_advocate}` | Date: `{sample_date}`"
            )

    # 3. Dry-Run Check
    if not apply_changes:
        print("=== DRY RUN (No files modified) ===")
        print(f"Planned writes ({len(staged_file_writes)} files):")
        for path in staged_file_writes:
            print(f"  - {path}")
        print("\nPlanned changelog entries:")
        for entry in changelog_entries:
            print(f"  {entry}")
        print("\nPass --apply to execute these changes atomically.")
        return len(staged_file_writes)

    # 4. Atomic Execution with Rollback on Error
    backups: dict[Path, str | None] = {}
    for target in staged_file_writes:
        backups[target] = target.read_text(encoding="utf-8") if target.exists() else None

    written: list[Path] = []
    try:
        for target, content in staged_file_writes.items():
            target.write_text(content, encoding="utf-8")
            written.append(target)

        # Write Changelog
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry_lines = [
            f"## Verification Applied: {now_str}",
            f"Applied by operator `{operator}` from `{csv_path}`",
            "",
            "### Changes:",
        ]
        entry_lines.extend(changelog_entries)
        entry_lines.append("\n---\n")

        if CHANGELOG_PATH.exists():
            existing = CHANGELOG_PATH.read_text(encoding="utf-8")
        else:
            existing = "# Rules Verification Changelog\n\nAudit log of advocate verifications applied to rules and configs.\n\n---\n\n"

        CHANGELOG_PATH.write_text(existing + "\n".join(entry_lines) + "\n", encoding="utf-8")

    except Exception as e:
        # Roll back all written files immediately
        for target in written:
            orig = backups.get(target)
            if orig is not None:
                target.write_text(orig, encoding="utf-8")
            elif target.exists():
                target.unlink()
        raise RuntimeError(f"Atomic update failed during {target.name}: {e}. All changes rolled back.") from e

    print(f"Successfully applied {len(staged_file_writes)} file update(s) atomically. Changelog updated at {CHANGELOG_PATH}.")
    return len(staged_file_writes)


def main():
    parser = argparse.ArgumentParser(description="Apply verified advocate review CSV.")
    parser.add_argument("csv_path", nargs="?", default=str(DOCS_DIR / "advocate_review_pack.csv"),
                        help="Path to the advocate review CSV")
    parser.add_argument("--apply", action="store_true", default=False,
                        help="Execute changes atomically. Default is dry-run.")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Perform validation without writing changes (default).")

    args = parser.parse_args()
    apply_mode = args.apply and not ("--dry-run" in sys.argv and "--apply" not in sys.argv)
    apply_review(Path(args.csv_path), apply_changes=apply_mode)


if __name__ == "__main__":
    main()
