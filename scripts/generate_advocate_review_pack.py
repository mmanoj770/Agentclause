#!/usr/bin/env python3
"""Generate the Advocate Review Pack (Markdown and CSV) from repository rule and config files.

Sources:
- backend/app/rules/config/*_required_clauses.json (4 contract types)
- backend/app/rules/rules/*.json (7 seed rules)
- backend/app/rules/config/seed_statutes.json (India Code URLs & CPC s.20)

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


def load_seed_statutes() -> list[dict]:
    path = CONFIG_DIR / "seed_statutes.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def generate():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    seed_statutes_list = load_seed_statutes()
    statute_lookup = {(s["act"].strip(), s["section"].strip()): s for s in seed_statutes_list}

    # 1. Load Rules and correlate with seed_statutes
    statutes_and_rules = []
    matched_seeds = set()

    for p in sorted(RULES_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        statute = data.get("statute", "")
        section = str(data.get("section", ""))

        india_code_url = ""
        staged_quote = data.get("basis", "")
        store = "rules"

        # Match in seed_statutes
        seed_match = None
        for (act, sec), stat in statute_lookup.items():
            if act.lower() in statute.lower() and sec.lower() == section.lower():
                seed_match = stat
                matched_seeds.add((act, sec))
                break

        if seed_match:
            store = "rules + seed_statutes"
            india_code_url = seed_match.get("source_url", "")
            if not staged_quote or staged_quote == "(none staged)":
                staged_quote = seed_match.get("statute_text", "")
        else:
            if "Indian Contract Act" in statute:
                india_code_url = "https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362"
            elif "Micro, Small and Medium" in statute:
                india_code_url = "https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362"
            else:
                india_code_url = "N/A (Internal Baseline)"

        statutes_and_rules.append({
            "category": "seed_rule",
            "file": p.name,
            "identifier": data["rule_id"],
            "store": store,
            "statute": statute,
            "section": section,
            "staged_quote": staged_quote or "(none staged)",
            "india_code_url": india_code_url,
            "plain_english_logic": data.get("description", ""),
            "remedy": data.get("remedy_suggested", ""),
            "severity": data.get("severity", ""),
            "applies_to": ", ".join(data.get("applies_to", [])),
        })

    # 2. Add seed_statutes rows not covered by rules (e.g. CPC s. 20)
    for stat in seed_statutes_list:
        key = (stat["act"].strip(), stat["section"].strip())
        if key not in matched_seeds:
            statutes_and_rules.append({
                "category": "statute",
                "file": "seed_statutes.json",
                "identifier": f"STATUTE_{stat['act'][:3].upper()}_S{stat['section']}",
                "store": "seed_statutes",
                "statute": stat["act"],
                "section": stat["section"],
                "staged_quote": stat.get("statute_text", ""),
                "india_code_url": stat.get("source_url", "https://www.indiacode.nic.in"),
                "plain_english_logic": f"{stat.get('heading', '')} (Jurisdiction baseline)",
                "remedy": "Ensure governing law and court submission clauses align with civil procedure jurisdiction limits.",
                "severity": "high",
                "applies_to": "all (jurisdiction baseline)",
            })

    # 3. Load Contract Types & Required Clauses
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
            "store",
            "contract_type_or_applies_to",
            "statute_or_context",
            "section_or_clause",
            "staged_quote_or_description",
            "india_code_url",
            "plain_english_logic",
            "verified",
            "advocate_name",
            "verification_date",
            "verification_ref",
            "corrected_quote",
            "notes",
            "verified / corrected quote / notes",
        ])

        # Write seed rules & statutes
        for r in statutes_and_rules:
            writer.writerow([
                r["category"],
                r["identifier"],
                r["store"],
                r["applies_to"],
                r["statute"],
                r["section"],
                r["staged_quote"],
                r["india_code_url"],
                r["plain_english_logic"],
                "",  # verified (blank for advocate)
                "",  # advocate_name
                "",  # verification_date
                "",  # verification_ref
                "",  # corrected_quote
                "",  # notes
                "",  # combined legacy notes
            ])

        # Write required clauses
        for c_id, label, cfg in contract_configs:
            for req in cfg.get("required", []):
                writer.writerow([
                    "required_clause",
                    f"{c_id}:{req['clause']}",
                    "completeness_config",
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
                    "",
                    "",
                    "",
                ])

    # --- Generate Markdown ---
    md_path = DOCS_DIR / "advocate_review_pack.md"
    lines = [
        "# Advocate Review Pack (R3 Completeness, R5 Seed Rules & Database Statutes)",
        "",
        "> [!IMPORTANT]",
        "> **For Verifying Advocate / Legal Counsel**:",
        "> This review pack is compiled automatically from the AgentClause repository configurations, rule files,",
        "> and database seed statutes. In accordance with platform governance, production strict mode returns zero",
        "> findings on unverified rules until a licensed Indian advocate verifies these quotes against authoritative",
        "> sources (India Code) and confirms the required clauses.",
        "",
        "## Review Instructions",
        "1. **Statutory Quotes (R5 & Database Statutes)**: Open each India Code URL and check whether the staged quote matches the operative statutory text word-for-word. Note any corrections.",
        "2. **Required Clause Lists (R3)**: Confirm that the mandatory clause lists reflect standard practice and legal enforceability under Indian law.",
        "3. **Sign-off**: Mark verified rows in `docs/advocate_review_pack.csv` with `verified` = `yes`, `advocate_name` = `<Your Name>`, and `verification_date` = `<YYYY-MM-DD>`.",
        "",
        "---",
        "",
        f"## Part 1: Statutory Seed Rules & Database Statutes ({len(statutes_and_rules)} Entries)",
        "",
    ]

    for i, r in enumerate(statutes_and_rules, 1):
        lines.extend([
            f"### {i}. `{r['identifier']}` ({r['statute']}, s. {r['section']})",
            f"- **Store**: `{r['store']}`",
            f"- **Severity**: `{r['severity']}` | **Applies To**: {r['applies_to']}",
            f"- **India Code Verification URL**: [{r['india_code_url']}]({r['india_code_url']})",
            f"- **Rule Logic / Heading**: {r['plain_english_logic']}",
            f"- **Remedy Suggested**: {r['remedy']}",
            "- **Staged Quote**:",
            "  > " + r['staged_quote'].replace("\n", "\n  > "),
            "",
            "| Verified (Yes/No) | Advocate Name | Date (YYYY-MM-DD) | Corrected Quote (if any) | Notes |",
            "| :---: | :---: | :---: | :--- | :--- |",
            "| [ ] | | | | |",
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
            f"- **Store**: `completeness_config`",
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
