"""Unit tests for Advocate Review Pack generator and apply script (R3 + R5)."""
import csv
import json
import shutil
import sys
from pathlib import Path

# Ensure repo root is in sys.path to import from scripts
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

import scripts.apply_advocate_review as apply_script
import scripts.generate_advocate_review_pack as gen_script


def test_generate_advocate_review_pack(tmp_path, monkeypatch):
    docs_tmp = tmp_path / "docs"
    monkeypatch.setattr(gen_script, "DOCS_DIR", docs_tmp)

    md_path, csv_path = gen_script.generate()
    assert md_path.exists()
    assert csv_path.exists()

    # Read CSV
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    rules_in_csv = [r for r in reader if r["category"] == "seed_rule"]
    statutes_in_csv = [r for r in reader if r["category"] == "statute"]
    clauses_in_csv = [r for r in reader if r["category"] == "required_clause"]

    # Exactly 7 seed rules + 1 seed statute (CPC s. 20)
    assert len(rules_in_csv) == 7
    assert len(statutes_in_csv) == 1
    rule_ids = {r["identifier"] for r in rules_in_csv}
    assert "ICA_S27_RESTRAINT_OF_TRADE" in rule_ids
    assert "ICA_S28_RESTRAINT_OF_LEGAL_PROCEEDINGS" in rule_ids
    assert "ICA_S74_PENALTY_OR_LIQUIDATED_DAMAGES" in rule_ids
    assert "MSMED_S15_PAYMENT_BEYOND_45_DAYS" in rule_ids
    assert "MSMED_S16_INTEREST_WAIVER" in rule_ids
    assert "NDA_CONFIDENTIAL_INFO_DEFINITION_MISSING" in rule_ids
    assert "NDA_GOVERNING_LAW_MISSING" in rule_ids

    # Store column present and accurate
    assert all("store" in r and r["store"] for r in reader)
    assert any(r["store"] == "seed_statutes" for r in reader)
    assert any(r["store"] == "rules + seed_statutes" for r in reader)

    # Required clauses for all 4 contract types
    contract_types_in_csv = {r["contract_type_or_applies_to"] for r in clauses_in_csv}
    assert {"nda", "vendor_supplier", "founders_agreement", "sha"} <= contract_types_in_csv

    # Verification columns are initially blank
    for r in reader:
        assert r["verified"] == ""

    # Read Markdown
    md_content = md_path.read_text(encoding="utf-8")
    assert "# Advocate Review Pack (R3 Completeness, R5 Seed Rules & Database Statutes)" in md_content
    assert "ICA_S27_RESTRAINT_OF_TRADE" in md_content
    assert "https://www.indiacode.nic.in" in md_content


def test_apply_advocate_review_on_blank_csv_changes_nothing(tmp_path, monkeypatch):
    csv_path = tmp_path / "blank.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "identifier", "verified", "corrected_quote", "notes"])
        writer.writerow(["seed_rule", "ICA_S27_RESTRAINT_OF_TRADE", "", "", ""])

    applied = apply_script.apply_review(csv_path)
    assert applied == 0


def test_apply_advocate_review_flips_only_verified_rows_in_isolation(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    # Create dummy rule file
    rule_file = rules_dir / "test_rule.json"
    rule_file.write_text(json.dumps({
        "rule_id": "TEST_RULE_1",
        "basis": "Original quote",
        "verification_status": "unverified"
    }))

    # Create dummy config file
    cfg_file = config_dir / "nda_required_clauses.json"
    cfg_file.write_text(json.dumps({
        "contract_type": "nda",
        "verification_status": "unverified",
        "required": [{"clause": "confidentiality", "severity": "high"}]
    }))

    monkeypatch.setattr(apply_script, "RULES_DIR", rules_dir)
    monkeypatch.setattr(apply_script, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(apply_script, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(apply_script, "CHANGELOG_PATH", docs_dir / "rules_verification_changelog.md")

    # Write CSV with 1 verified rule with corrected quote, and 1 verified clause
    test_csv = tmp_path / "completed_review.csv"
    with open(test_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["category", "identifier", "verified", "corrected_quote", "notes", "verified / corrected quote / notes"])
        writer.writerow(["seed_rule", "TEST_RULE_1", "yes", "Corrected statutory quote", "Advocate Sharma sign-off", ""])
        writer.writerow(["required_clause", "nda:confidentiality", "yes", "", "Standard clause", ""])

    applied = apply_script.apply_review(test_csv)
    assert applied == 2

    # Verify rule was updated
    updated_rule = json.loads(rule_file.read_text())
    assert updated_rule["verification_status"] == "verified"
    assert updated_rule["basis"] == "Corrected statutory quote"

    # Verify config was updated
    updated_cfg = json.loads(cfg_file.read_text())
    assert updated_cfg["verification_status"] == "verified"

    # Verify changelog was written
    changelog = (docs_dir / "rules_verification_changelog.md").read_text()
    assert "Verification Applied:" in changelog
    assert "TEST_RULE_1" in changelog
    assert "Advocate Sharma sign-off" in changelog


def test_repo_shipped_rules_and_configs_remain_strictly_unverified():
    """Verify that none of the actual repository rules or completeness configs were modified to verified."""
    repo_rules_dir = Path(__file__).resolve().parents[1] / "app" / "rules" / "rules"
    repo_config_dir = Path(__file__).resolve().parents[1] / "app" / "rules" / "config"

    for r_file in repo_rules_dir.glob("*.json"):
        data = json.loads(r_file.read_text(encoding="utf-8"))
        assert data.get("verification_status") == "unverified", f"{r_file.name} must remain unverified"

    for c_file in repo_config_dir.glob("*_required_clauses.json"):
        data = json.loads(c_file.read_text(encoding="utf-8"))
        assert data.get("verification_status") == "unverified", f"{c_file.name} must remain unverified"
