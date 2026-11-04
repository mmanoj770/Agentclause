#!/usr/bin/env python3
"""Generate the Advocate Review Pack (Markdown and CSV) from repository rule and config files.

Sources:
- backend/app/rules/config/*_required_clauses.json (4 contract types)
- backend/app/rules/rules/*.json (7 seed rules)
- backend/app/rules/config/seed_statutes.json (India Code URLs)

Outputs:
- docs/advocate_review_pack.md
- docs/advocate_review_pack.csv
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "backend" / "app" / "rules" / "rules"
CONFIG_DIR = ROOT / "backend" / "app" / "rules" / "config"
DOCS_DIR = ROOT / "docs"

CONTRACT_TYPES = [
    ("nda", "Non-Disclosure Agreement (NDA)", CONFIG_DIR / "nda_required_clauses.json"),
    ("vendor_supplier", "Vendor / Supplier Agreement", CONFIG_DIR / "vendor_supplier_required_clauses.json"),
    ("founders_agreement", "Founders' Agreement", CONFIG_DIR / "founders_agreement_required_clauses.json"),
    ("sha", "Shareholders' Agreement (SHA)", CONFIG_DIR / "sha_required_clauses.json"),
]


def load_seed_statutes() -> dict[tuple[str, str], dict]:
    path = CONFIG_DIR / "seed_statutes.json"
    if not path.exists():
        return {}
    items = json.loads(path.read_text(encoding="utf-8"))
    lookup = {}
    for item in items:
        lookup[(item["act"].strip(), item["section"].strip())] = item
    return lookup


def generate():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    statute_lookup = load_seed_statutes()

    # 1. Load Rules
    rules = []
    for p in sorted(RULES_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        statute = data.get("statute", "")
        section = data.get("section", "")
        india_code_url = ""
        # Match statute in lookup
        for (act, sec), stat in statute_lookup.items():
            if act.lower() in statute.lower() and sec.lower() == section.lower():
                india_code_url = stat.get("source_url", "")
                break
        if not india_code_url:
            if "Indian Contract Act" in statute:
                india_code_url = "https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362"
            elif "Micro, Small and Medium" in statute:
                india_code_url = "https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362"
            else:
                india_code_url = "N/A (Internal Baseline)"

        rules.append({
            "file": p.name,
            "rule_id": data["rule_id"],
            "statute": statute,
            "section": section,
            "staged_quote": data.get("basis", "(none staged)"),
            "india_code_url": india_code_url,
            "plain_english_logic": data.get("description", ""),
            "remedy": data.get("remedy_suggested", ""),
            "severity": data.get("severity", ""),
            "applies_to": ", ".join(data.get("applies_to", [])),
        })

    # 2. Load Contract Types & Required Clauses
    contract_configs = []
    for c_id, label, path in CONTRACT_TYPES:
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8"))
            contract_configs.append((c_id, label, cfg))

    # --- Generate CSV ---
    csv_path = DOCS_DIR / "advocate_review_pack.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "category",
            "identifier",
            "contract_type_or_applies_to",
            "statute_or_context",
            "section_or_clause",
            "staged_quote_or_description",
            "india_code_url",
            "plain_english_logic",
            "verified",
            "corrected_quote",
            "notes",
            "verified / corrected quote / notes",
        ])

        # Write seed rules
        for r in rules:
            writer.writerow([
                "seed_rule",
                r["rule_id"],
                r["applies_to"],
                r["statute"],
                r["section"],
                r["staged_quote"],
                r["india_code_url"],
                r["plain_english_logic"],
                "",  # verified (blank for advocate)
                "",  # corrected_quote
                "",  # notes
                "",  # verified / corrected quote / notes
            ])

        # Write required clauses
        for c_id, label, cfg in contract_configs:
            for req in cfg.get("required", []):
                writer.writerow([
                    "required_clause",
                    f"{c_id}:{req['clause']}",
                    c_id,
                    label,
                    req["clause"],
                    f"Required clause ({req.get('severity', 'medium')})",
                    "N/A (Contract Baseline)",
                    f"Must be present in valid Indian {label}",
                    "",  # verified
                    "",
                    "",
                    "",
                ])

    # --- Generate Markdown ---
    md_path = DOCS_DIR / "advocate_review_pack.md"
    lines = [
        "# Advocate Review Pack (R3 Completeness & R5 Seed Rules)",
        "",
        "> [!IMPORTANT]",
        "> **For Verifying Advocate / Legal Counsel**:",
        "> This review pack is compiled automatically from the AgentClause repository configurations and rule files.",
        "> In accordance with platform governance, production strict mode returns zero findings on unverified rules until",
        "> a licensed Indian advocate verifies these quotes against authoritative sources (India Code) and confirms the required clauses.",
        "",
        "## Review Instructions",
        "1. **Statutory Quotes (R5)**: Open each India Code URL and check whether the staged quote matches the operative statutory text word-for-word. Note any corrections.",
        "2. **Required Clause Lists (R3)**: Confirm that the mandatory clause lists reflect standard practice and legal enforceability under Indian law.",
        "3. **Sign-off**: Mark verified rows in `docs/advocate_review_pack.csv` with `verified` = `yes` and provide your name, Bar Council enrollment number, and date.",
        "",
        "---",
        "",
        "## Part 1: Statutory Seed Rules (7 Rules)",
        "",
    ]

    for i, r in enumerate(rules, 1):
        lines.extend([
            f"### {i}. Rule `{r['rule_id']}`",
            f"- **Statute & Section**: {r['statute']}, s. {r['section']}",
            f"- **Severity**: `{r['severity']}` | **Applies To**: {r['applies_to']}",
            f"- **India Code Verification URL**: [{r['india_code_url']}]({r['india_code_url']})",
            f"- **Rule Logic**: {r['plain_english_logic']}",
            f"- **Remedy Suggested**: {r['remedy']}",
            "- **Staged Quote**:",
            "  > " + r['staged_quote'].replace("\n", "\n  > "),
            "",
            "| Verified (Yes/No) | Corrected Quote (if any) | Advocate Notes |",
            "| :---: | :--- | :--- |",
            "| [ ] | | |",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## Part 2: Required Clauses by Contract Type (4 Types)",
        "",
    ])

    for c_id, label, cfg in contract_configs:
        lines.extend([
            f"### Contract Type: {label} (`{c_id}`)",
            f"- **Current Verification Status**: `{cfg.get('verification_status', 'unverified')}`",
            f"- **Total Required Clauses**: {len(cfg.get('required', []))}",
            "",
            "| Clause Key | Severity | Description / Purpose | Verified Enforceability Baseline |",
            "| :--- | :---: | :--- | :---: |",
        ])
        for req in cfg.get("required", []):
            lines.append(f"| `{req['clause']}` | `{req.get('severity', 'medium')}` | Standard mandatory clause | [ ] |")
        lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return md_path, csv_path


if __name__ == "__main__":
    generate()
