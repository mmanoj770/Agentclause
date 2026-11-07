# AgentClause: Project Status (Backend & Review Agent)

**Status as of**: 7 November 2026  
**Repository Branch**: `blockers-prep` (Commit `885c114`, pushed to `origin/blockers-prep`)  
**Base Commit**: `origin/main` (`41fbc94`)  
**Backend Test Suite**: **1001 passed, 38 skipped, 0 failed** in 7.80s (31 access test skips needing live tokens + 7 known skipped tests)  
**Live Database**: Supabase (`pmrkwctwjqhrhkwtjrbz`, `ap-south-1` Mumbai) · 21 migrations live and verified

---

## Executive Summary

1. **Review Agent (R1–R11) Architecture Complete in Code**:
   - The entire Review Agent pipeline is merged, tested, and runnable end-to-end.
   - **Demo Mode (`strict=False`)**: Fully functional. Ingests contracts, detects missing mandatory clauses, verifies Indian statutory compliance (ICA, MSMED Act, CPC), scores one-sided risk asymmetry, gates citations, triages document risk tiers, and transitions states to `pending_lawyer_review`. Detects 6/6 planted defects in synthetic test fixtures (`nda_bad`, `nda_clean`, `vendor_msme`).
   - **Strict Mode (`strict=True`, Production Default)**: Fully active and fails safe. Evaluates only verified rules. Because seed statutory quotes and clause configurations await advocate sign-off, the engine cleanly skips unverified rules and returns an explicit `review_status="no_rules_verified"` with `rules_evaluated=0` and full `coverage` metadata. It **never** gives unverified contracts a false "clean bill of health".

2. **All Engineering Blocker Tasks Completed & Pushed on `blockers-prep`**:
   - **Task 1 (Sample Provenance)**: Renamed `sample_gem_procurement` to `sample_stub` and isolated synthetic stubs from aggregate metrics in [`scripts/benchmark_public_contracts.py`](file:///Users/manojmj/Agentclause/scripts/benchmark_public_contracts.py).
   - **Task 2 (Single Source of Truth for Statute Quotes)**: Implemented `normalize_statute_quote()`, dual-store parity assertions between `rules/` and `seed_statutes.json`, codified known asymmetries (CPC s. 20), and added store tracking columns in [`docs/advocate_review_pack.csv`](file:///Users/manojmj/Agentclause/docs/advocate_review_pack.csv).
   - **Task 3 (Advocate Review Applier Safety Guards)**: Added atomic dual-store updates, in-memory rollback on failure, `--dry-run` and `--apply` flags, mandatory advocate name/date validation, and quote-modification refusal without an India Code URL in [`scripts/apply_advocate_review.py`](file:///Users/manojmj/Agentclause/scripts/apply_advocate_review.py).
   - **Task 4 (Statute Edit Guard Migration 22)**: Created [`supabase/migrations/20261105100000_22_statutes_verified_guard.sql`](file:///Users/manojmj/Agentclause/supabase/migrations/20261105100000_22_statutes_verified_guard.sql) (file only) with a `BEFORE UPDATE` trigger demoting modified verified quotes to `staging`, plus [`scripts/preflight_22.sql`](file:///Users/manojmj/Agentclause/scripts/preflight_22.sql).
   - **Task 5 (Statute Verification Tooling & Section Matching)**: Hardened [`scripts/verify_statute.py`](file:///Users/manojmj/Agentclause/scripts/verify_statute.py) with mandatory advocate credentials and audit logging; hardened [`scripts/load_statutes.py`](file:///Users/manojmj/Agentclause/scripts/load_statutes.py) with per-row SHA-256 drift detection; implemented `section_matches()` in [`backend/app/statutes/normalizer.py`](file:///Users/manojmj/Agentclause/backend/app/statutes/normalizer.py) and exported from [`app.statutes`](file:///Users/manojmj/Agentclause/backend/app/statutes/__init__.py) with specification in [`docs/statutes_matching_rule.md`](file:///Users/manojmj/Agentclause/docs/statutes_matching_rule.md).
   - **Task 6 (Intake PII Redaction Hardening)**: Hardened DPDP redaction regexes in [`backend/app/intake/service.py`](file:///Users/manojmj/Agentclause/backend/app/intake/service.py) protecting Indian currencies (`12,50,000`, `Rs. 5,00,000`, `INR 1,25,00,000`), clause numbers, dates, and invoice IDs; added automatic retry on garbled/altered placeholders (`[PAN_1]` -> `[PAN_2]`); updated [`docs/dpdp_intake_note.md`](file:///Users/manojmj/Agentclause/docs/dpdp_intake_note.md) with explicit disclosure of unredacted entities.
   - **Task 7 (Safe Failure Surfaces)**: Handled R7 `side=None` returning `side_unknown=True` and 0.0 score; added `provisional=True` flags in R7 asymmetry, R9 triage, and `/queue` when configs are `PLACEHOLDER`; propagated `coverage` and `review_status` to API schemas; verified strict mode returns `review_status="no_rules_verified"` on synthetic fixtures.
   - **Task 8 (Expiration Guard Test)**: Added automated CI test in [`backend/tests/test_finding_views.py`](file:///Users/manojmj/Agentclause/backend/tests/test_finding_views.py) failing CI starting November 8, 2026 if `ID_ALIAS_UNTIL` (2026-11-15) is not removed or extended.
   - **Task 9 (Outreach Packs & Master Tracking Table)**: Prepared dedicated outreach briefs in [`docs/outreach/`](file:///Users/manojmj/Agentclause/docs/outreach/) (`advocate.md`, `arjun.md`, `tejaswi.md`, `poornaa.md`, `compliance.md`) and centralized human action items in [`docs/HUMAN_ACTIONS.md`](file:///Users/manojmj/Agentclause/docs/HUMAN_ACTIONS.md).

3. **Zero Premature Verifications**: All legal rules, quotes, and configs remain strictly `unverified` pending advocate sign-off.

---

## 1. At a Glance Matrix

| Area | Current State | Target / Blocker |
|---|---|---|
| **Backend Core** | Done, on `main` | Auth, documents, S3 storage, findings, queue, audit operational. |
| **Database** | Live & healthy | 21 migrations live. Migration 22 prepared (file only). |
| **Review Agent (R1–R11)** | Complete in code | Demo mode 100% operational; Strict mode fails safe pending sign-offs. |
| **Blockers Branch** | `blockers-prep` (`885c114`) | 17 commits ahead of `main`; PR ready for review and merge. |
| **Test Suite** | **1001 passed, 38 skipped, 0 failed** | Zero failures permitted; full suite green in 7.80s. |
| **Advocate Review Pack** | Prepared & guarded | `advocate_review_pack.csv` & `.md` ready; apply script guarded. |
| **Human Actions Matrix** | Fully mapped | 11 tracked items across Advocate, Tejaswi, Arjun, Poornaa, Compliance, Counsel. |

---

## 2. Review Agent (R1–R11 Layer Breakdown)

| Layer | Component | Status | Implementation Details |
|---|---|---|---|
| **R1** | Finding Schema | **Done** | [`app/schemas/finding.py`](file:///Users/manojmj/Agentclause/backend/app/schemas/finding.py) defines universal finding contract across all review layers. |
| **R2** | Intake & Normalisation | **Done** | Client-side DPDP PII redaction (`INTAKE_REDACT_PII`) before LLM calls; hardened against currencies/dates/invoices; retry on altered tokens; verbatim substring verification against original contract text. |
| **R3** | Completeness Checker | **Done (Code)** | Shipped configs for **NDA**, **Vendor/Supplier**, **Founders' Agreement**, and **SHA**. Implements `check_with_coverage()` reporting `rules_total`, `rules_evaluated`, `rules_skipped_unverified`, and explicit `review_status`. |
| **R4** | Rule Engine | **Done** | Date-versioned rule evaluator against normalized text, Indian date handling, clause references, and `evaluate_with_coverage()`. |
| **R5** | Statutory Rules Content | **Done (Code)** | 7 seed statutory rules staged (ICA ss. 27, 28, 74; MSMEDA ss. 15, 16; CPC s. 20). Staged as `unverified`; single source of truth test verifies parity between `rules/` and `seed_statutes.json`. |
| **R6** | Cross-Clause Consistency | **Done (Code)** | Detects conflicting facts/periods across clauses. Severities capped at `low` while config is placeholder. |
| **R7** | Risk Asymmetry | **Done (Code)** | Robust org-name normalization (`normalize_org_name`: casefold, M/s, honorifics, &, punctuation, Pvt/Ltd/LLP canonicalization), and conservative fuzzy matching with logging. Ambiguous/missing party matches return `side_unknown=True` and 0.0 score. |
| **R8** | Citation Gate | **In Progress** | Write-time screening: `public.statutes` table live (Migration 21); trigger guard migration 22 ready; `section_matches()` exported from `app.statutes`. Awaiting Arjun's DB lookup wiring and Poornaa's clause manifest. |
| **R9** | Risk Triage | **Done (Code)** | Computes document `triage_tier` (`tier_1_urgent`, `tier_2_standard`, `tier_3_routine`) based on severity points and R7 asymmetry score. Flags `provisional=True` when weights are placeholder. Lawyer queue supports sorting by tier. |
| **R10** | Pipeline Runner | **Done** | Background orchestration (`runner.py`), transaction rollbacks on failure, `recover_stale_reviews()` in FastAPI lifespan, audit logs recording layer timings, counts, coverage, and review status. |
| **R11** | Evaluation & Benchmarking | **Done** | Synthetic fixtures in `backend/tests/fixtures/contracts/` (finds 6/6 in demo mode; reports `no_rules_verified` in strict mode). Public benchmark runner (`scripts/benchmark_public_contracts.py`) isolates synthetic stubs (`sample_stub`). |

---

## 3. Human Actions & Blocker Resolution Roadmap

All technical preparations are complete. Production readiness requires completion of the following human-only actions tracked in [`docs/HUMAN_ACTIONS.md`](file:///Users/manojmj/Agentclause/docs/HUMAN_ACTIONS.md):

| Item # | Owner | Task & Deliverable | Blocking Layers | Prepared Tools / Artifacts |
|:---:|:---|:---|:---:|:---|
| **HA-01** | **Advocate** (Legal Counsel) | Verify 7 statutory seed quotes against India Code | **R4, R5, R8** | [`docs/advocate_review_pack.csv`](file:///Users/manojmj/Agentclause/docs/advocate_review_pack.csv)<br>[`scripts/apply_advocate_review.py`](file:///Users/manojmj/Agentclause/scripts/apply_advocate_review.py)<br>[`docs/outreach/advocate.md`](file:///Users/manojmj/Agentclause/docs/outreach/advocate.md) |
| **HA-02** | **Advocate** (Legal Counsel) | Sign off on mandatory NDA clause list | **R3** | [`nda_required_clauses.json`](file:///Users/manojmj/Agentclause/backend/app/rules/config/nda_required_clauses.json)<br>[`docs/advocate_review_pack.md`](file:///Users/manojmj/Agentclause/docs/advocate_review_pack.md) |
| **HA-03** | **Compliance / DPO** | Sign off on DPDP Section 16 data transit & customer consent | **R2, R10** | [`docs/dpdp_intake_note.md`](file:///Users/manojmj/Agentclause/docs/dpdp_intake_note.md)<br>[`docs/outreach/compliance.md`](file:///Users/manojmj/Agentclause/docs/outreach/compliance.md) |
| **HA-04** | **Arjun** | Wire Citation Gate to `public.statutes` table | **R8** | [`docs/statutes_matching_rule.md`](file:///Users/manojmj/Agentclause/docs/statutes_matching_rule.md)<br>[`app.statutes.section_matches`](file:///Users/manojmj/Agentclause/backend/app/statutes/normalizer.py)<br>[`docs/outreach/arjun.md`](file:///Users/manojmj/Agentclause/docs/outreach/arjun.md) |
| **HA-05** | **Arjun** | Finding citation token extraction & case-law index | **R8** | [`docs/outreach/arjun.md`](file:///Users/manojmj/Agentclause/docs/outreach/arjun.md) |
| **HA-06** | **Poornaa** | Provide structured clause manifest schema (R8 #7) | **R6, R7, R8** | [`docs/outreach/poornaa.md`](file:///Users/manojmj/Agentclause/docs/outreach/poornaa.md) |
| **HA-07** | **Legal Counsel** (Partner) | Calibrate risk triage weights (`triage.json`) | **R9** | [`backend/app/pipeline/config/triage.json`](file:///Users/manojmj/Agentclause/backend/app/pipeline/config/triage.json) |
| **HA-08** | **Legal Counsel** (Partner) | Calibrate risk asymmetry provision weights (`asymmetry.json`) | **R7** | [`backend/app/pipeline/config/asymmetry.json`](file:///Users/manojmj/Agentclause/backend/app/pipeline/config/asymmetry.json) |
| **HA-09** | **Tejaswi** | Deploy migrations 20, 21, and 22 during deploy window | **All DB** | [`20261105100000_22_statutes_verified_guard.sql`](file:///Users/manojmj/Agentclause/supabase/migrations/20261105100000_22_statutes_verified_guard.sql)<br>[`scripts/preflight_21.sql`](file:///Users/manojmj/Agentclause/scripts/preflight_21.sql)<br>[`scripts/preflight_22.sql`](file:///Users/manojmj/Agentclause/scripts/preflight_22.sql) |
| **HA-10** | **Tejaswi** | Review and merge PR `blockers-prep` into `main` | **Main Branch** | [PR Link](https://github.com/mmanoj770/Agentclause/pull/new/blockers-prep)<br>[`docs/outreach/tejaswi.md`](file:///Users/manojmj/Agentclause/docs/outreach/tejaswi.md) |
| **HA-11** | **Engineering** | Deprecate Finding `id` alias before November 15, 2026 | **API Schemas** | [`backend/tests/test_finding_views.py`](file:///Users/manojmj/Agentclause/backend/tests/test_finding_views.py) |

---

## 4. Verification and Pull Request

- **PR Branch**: `blockers-prep`
- **PR URL**: `https://github.com/mmanoj770/Agentclause/pull/new/blockers-prep`
- **Commits Ahead of Main**: 17 commits
- **Test Suite Verification**:
  ```bash
  cd backend && PYTHONPATH=. .venv/bin/pytest -q tests
  # 1001 passed, 38 skipped, 0 failed in 7.80s
  ```
