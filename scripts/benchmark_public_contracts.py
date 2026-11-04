#!/usr/bin/env python3
"""Public Contract Benchmark Runner (R11).

Evaluates the AgentClause review layers on public domain, anonymized contracts
stored in backend/tests/fixtures/public_contracts/.

Outputs a clean summary table of:
- Layer-by-layer findings (R3 Completeness, R4/R5 Rules)
- Strict mode coverage and review_status
- Execution runtime per contract
"""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.intake.service import clean_text
from app.rules.api import run_review
from app.schemas.finding import Layer

DEFAULT_PUBLIC_DIR = BACKEND_DIR / "tests" / "fixtures" / "public_contracts"


def load_public_contracts(directory: Path | None = None) -> list[dict]:
    """Load benchmark contracts and optional metadata from the public contracts directory."""
    path = directory or DEFAULT_PUBLIC_DIR
    if not path.exists():
        return []

    contracts = []
    for txt_file in sorted(path.glob("*.txt")):
        meta_file = txt_file.with_suffix(".meta.json")
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                meta = {}

        contracts.append({
            "name": txt_file.stem,
            "path": txt_file,
            "text": txt_file.read_text(encoding="utf-8"),
            "doc_type": meta.get("document_type", "vendor_supplier"),
            "meta": meta,
        })
    return contracts


def run_benchmark(directory: Path | None = None, *, strict: bool = True) -> dict:
    """Run benchmark review on all contracts in the directory. Gracefully handles 0 contracts."""
    contracts = load_public_contracts(directory)
    if not contracts:
        msg = f"No public contracts found in {directory or DEFAULT_PUBLIC_DIR} (0 contracts benchmarked)."
        return {
            "total": 0,
            "strict": strict,
            "results": [],
            "summary_table": msg,
        }

    results = []
    for c in contracts:
        t0 = time.monotonic()
        cleaned = clean_text(c["text"])
        res = asyncio.run(run_review(cleaned, c["doc_type"], strict=strict))
        runtime_ms = round((time.monotonic() - t0) * 1000, 1)

        completeness_findings = [f for f in res.findings if f.layer == Layer.COMPLETENESS]
        statutory_findings = [f for f in res.findings if f.layer == Layer.STATUTORY_RULES]

        results.append({
            "name": c["name"],
            "doc_type": c["doc_type"],
            "runtime_ms": runtime_ms,
            "findings_count": len(res.findings),
            "completeness_findings": len(completeness_findings),
            "statutory_findings": len(statutory_findings),
            "coverage": res.coverage.model_dump(),
            "review_status": res.coverage.review_status,
        })

    # Build summary table
    table_lines = [
        f"Public Contract Benchmark Set (Total: {len(results)}, Strict: {strict})",
        "=" * 96,
        f"{'Contract Name':<30} | {'Type':<15} | {'Findings':<10} | {'Coverage (Eval/Tot)':<20} | {'Status':<15} | {'Runtime'}",
        "-" * 96,
    ]
    for r in results:
        cov = r["coverage"]
        cov_str = f"{cov['rules_evaluated']}/{cov['rules_total']}"
        findings_str = f"{r['findings_count']} (C:{r['completeness_findings']}, S:{r['statutory_findings']})"
        table_lines.append(
            f"{r['name']:<30} | {r['doc_type']:<15} | {findings_str:<10} | {cov_str:<20} | {r['review_status']:<15} | {r['runtime_ms']} ms"
        )
    table_lines.append("=" * 96)
    summary_table = "\n".join(table_lines)

    return {
        "total": len(results),
        "strict": strict,
        "results": results,
        "summary_table": summary_table,
    }


def main():
    res = run_benchmark(strict=True)
    print(res["summary_table"])
    # Also print demo mode if requested
    if "--demo" in sys.argv:
        demo_res = run_benchmark(strict=False)
        print("\n" + demo_res["summary_table"])


if __name__ == "__main__":
    main()
