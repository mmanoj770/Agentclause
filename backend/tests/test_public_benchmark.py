"""Unit tests for Public Contract Benchmark Set (R11)."""
import sys
from pathlib import Path

# Ensure repo root in sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from scripts.benchmark_public_contracts import DEFAULT_PUBLIC_DIR, load_public_contracts, run_benchmark


def test_public_benchmark_empty_directory_graceful(tmp_path):
    empty_dir = tmp_path / "empty_public"
    empty_dir.mkdir()
    # Add only a README
    (empty_dir / "README.md").write_text("# Sourcing Guide\nOnly readme here.\n")

    contracts = load_public_contracts(empty_dir)
    assert contracts == []

    res = run_benchmark(empty_dir)
    assert res["total"] == 0
    assert res["results"] == []
    assert "0 contracts benchmarked" in res["summary_table"]


def test_public_benchmark_sample_contract_loads_and_runs():
    contracts = load_public_contracts(DEFAULT_PUBLIC_DIR)
    assert len(contracts) >= 1
    sample = next(c for c in contracts if c["name"] == "sample_stub")
    assert sample["doc_type"] == "vendor_supplier"
    assert sample["is_stub"] is True
    assert "GOVERNING LAW" in sample["text"]

    # Run in strict mode
    res_strict = run_benchmark(DEFAULT_PUBLIC_DIR, strict=True)
    assert res_strict["total"] >= 1
    assert res_strict["total_real"] == 0
    assert res_strict["total_stubs"] >= 1
    sample_res = next(r for r in res_strict["results"] if r["name"] == "sample_stub")
    assert sample_res["is_stub"] is True
    assert sample_res["review_status"] in ("no_rules_verified", "partial_unverified_rules")
    assert sample_res["runtime_ms"] > 0
    assert "sample_stub [SYNTHETIC STUB]" in res_strict["summary_table"]

    # Run in demo mode
    res_demo = run_benchmark(DEFAULT_PUBLIC_DIR, strict=False)
    sample_demo_res = next(r for r in res_demo["results"] if r["name"] == "sample_stub")
    assert sample_demo_res["review_status"] == "complete"

