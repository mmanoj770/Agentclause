# AgentClause: Project Status (Backend & Review Agent)

**Status as of**: 8 November 2026 (19:10 IST)  
**Repository Branch**: `blockers-prep` (Commit `08acbce`, pushed to `origin/blockers-prep`)  
**Base Commit**: `origin/main` (`41fbc94`)  
**Backend Test Suite**: **994 passed, 38 skipped, 0 failed** in 12.40s (31 access test skips needing live tokens + 7 known skipped tests)  
**Live Database**: Supabase (`pmrkwctwjqhrhkwtjrbz`, `ap-south-1` Mumbai) · 21 migrations live and verified  
**Authentication State**: **Legacy API keys disabled on live** · Publishable key (`sb_publishable_...`) active

---

## Executive Summary

1. **Legacy Key Disable Window (8 Nov 2026, 19:00–19:06 IST) — 100% PASS**:
   - **Legacy Keys Disabled**: Both the legacy `anon` (`eyJ...`) and legacy `service_role` (`eyJ...`) keys were disabled via toggle in the Supabase Dashboard.
   - **Local Environment Cutover**: `.env.local` and `.env.local.backup` were cleanly switched over to the new Supabase publishable key (`sb_publishable_CL7UK...`) with zero references to the legacy key remaining.
   - **Live Smoke & Isolation Verification**:
     - **Client Sign-in**: Fresh login succeeded; document upload and document list pages loaded cleanly.
     - **Advocate Sign-in**: Private-window login succeeded; dashboard and consultation request views loaded cleanly.
     - **`scripts/e2e_upload.py`**: **ALL PASS** (Tenant A and B uploads verified; cross-org upload-url, confirm, and download-url strictly refused with 403/404 in both directions with zero version leakage).
     - **`scripts/dry_run.py`**: **ALL PASS** (Full pipeline review, lawyer sign-off, client view sanitization, chat, and audit logging all passed; role permissions strictly enforced preventing lawyer from marking `delivered` with 403).
   - **Cleanup Tracking**: 3 test documents identified and tracked for post-window cleanup:
     1. `cd8387e9-10a3-4aa5-a98f-123779109df6`
     2. `26df2e7b-1128-461b-acd6-1ceaf24bb65b`
     3. `f009e905-ac8e-471d-9b2f-ae5ab1f298fb`
   - **Revocation Status**: Keys remain disabled overnight without incident; Arjun reviewing server logs tomorrow morning (Mon 9 Nov) before permanent revocation is scheduled.

2. **Review Agent (R1–R11) Operational Status**:
   - The entire Review Agent pipeline is merged, tested, and runnable end-to-end.
   - **Demo Mode (`strict=False`)**: Fully functional. Ingests contracts, detects missing mandatory clauses, verifies Indian statutory compliance (ICA, MSMED Act, CPC), scores one-sided risk asymmetry, gates citations, triages document risk tiers, and transitions states to `pending_lawyer_review`. Detects 6/6 planted defects in synthetic test fixtures (`nda_bad`, `nda_clean`, `vendor_msme`).
   - **Strict Mode (`strict=True`, Production Default)**: Fully active and fails safe. Evaluates only verified rules. Because seed statutory quotes and clause configurations await advocate sign-off, the engine cleanly skips unverified rules and returns an explicit `review_status="no_rules_verified"` with `rules_evaluated=0` and full `coverage` metadata. It **never** gives unverified contracts a false "clean bill of health".

3. **All Engineering Blocker Tasks Completed & Pushed on `blockers-prep`**:
   - **Task 1 (Sample Provenance)**: Renamed `sample_gem_procurement` to `sample_stub` and isolated synthetic stubs from aggregate metrics in [`scripts/benchmark_public_contracts.py`](file:///Users/manojmj/Agentclause/scripts/benchmark_public_contracts.py).
   - **Task 2 (Single Source of Truth for Statute Quotes)**: Implemented `normalize_statute_quote()`, dual-store parity assertions between `rules/` and `seed_statutes.json`, codified known asymmetries (CPC s. 20), and added store tracking columns in [`docs/advocate_review_pack.csv`](file:///Users/manojmj/Agentclause/docs/advocate_review_pack.csv).
   - **Task 3 (Advocate Review Applier Safety Guards)**: Added atomic dual-store updates, in-memory rollback on failure, `--dry-run` and `--apply` flags, mandatory advocate name/date validation, and quote-modification refusal without an India Code URL in [`scripts/apply_advocate_review.py`](file:///Users/manojmj/Agentclause/scripts/apply_advocate_review.py).
   - **Task 4 (Statute Edit Guard Migration 22)**: Created [`supabase/migrations/20261105100000_22_statutes_verified_guard.sql`](file:///Users/manojmj/Agentclause/supabase/migrations/20261105100000_22_statutes_verified_guard.sql) (file only) with a `BEFORE UPDATE` trigger demoting modified verified quotes to `staging`, plus [`scripts/preflight_22.sql`](file:///Users/manojmj/Agentclause/scripts/preflight_22.sql).
   - **Task 5 (Statute Verification Tooling & Section Matching)**: Hardened [`scripts/verify_statute.py`](file:///Users/manojmj/Agentclause/scripts/verify_statute.py) with mandatory advocate credentials and audit logging; hardened [`scripts/load_statutes.py`](file:///Users/manojmj/Agentclause/scripts/load_statutes.py) with per-row SHA-256 drift detection; implemented `section_matches()` in [`backend/app/statutes/normalizer.py`](file:///Users/manojmj/Agentclause/backend/app/statutes/normalizer.py) and exported from [`app.statutes`](file:///Users/manojmj/Agentclause/backend/app/statutes/__init__.py) with specification in [`docs/statutes_matching_rule.md`](file:///Users/manojmj/Agentclause/docs/statutes_matching_rule.md).
   - **Task 6 (Intake PII Redaction Hardening)**: Hardened DPDP redaction regexes in [`backend/app/intake/service.py`](file:///Users/manojmj/Agentclause/backend/app/intake/service.py) protecting Indian currencies (`12,50,000`, `Rs. 5,00,000`, `INR 1,25,00,000`), clause numbers, dates, and invoice IDs; added automatic retry on garbled/altered placeholders (`[PAN_1]` -> `[PAN_2]`); updated [`docs/dpdp_intake_note.md`](file:///Users/manojmj/Agentclause/docs/dpdp_intake_note.md) with explicit disclosure of unredacted entities.
   - **Task 7 (Safe Failure Surfaces)**: Handled R7 `side=None` returning `side_unknown=True` and 0.0 score; added `provisional=True` flags in R7 asymmetry, R9 triage, and `/queue` when configs are `PLACEHOLDER`; propagated `coverage` and `review_status` to API schemas; verified strict mode returns `review_status="no_rules_verified"` on synthetic fixtures.
   - **Task 8 (Finding `id` Alias Removal)**: Completed permanent removal of the deprecated `id` alias property and `ID_ALIAS_UNTIL` in [`backend/app/findings/schemas.py`](file:///Users/manojmj/Agentclause/backend/app/findings/schemas.py) per Tejaswi's directive (merged from `origin/arjun-alias`, commit `eec4e08`). All finding response models use `finding_id` only.
   - **Task 9 (Outreach Packs & Master Tracking Table)**: Prepared dedicated outreach briefs in [`docs/outreach/`](file:///Users/manojmj/Agentclause/docs/outreach/) (`advocate.md`, `arjun.md`, `tejaswi.md`, `poornaa.md`, `compliance.md`) and centralized human action items in [`docs/HUMAN_ACTIONS.md`](file:///Users/manojmj/Agentclause/docs/HUMAN_ACTIONS.md).
   - **Task 10 (Master Documentation)**: Compiled comprehensive [AgentClause Master Guide](file:///Users/manojmj/Agentclause/docs/AGENTCLAUSE_MASTER_GUIDE.md) detailing project history from Day 1, R1–R11 layer mechanics, security posture, and legal engineering fundamentals.

4. **Zero Premature Verifications**: All legal rules, quotes, and configs remain strictly `unverified` pending advocate sign-off.

---

## 1. At a Glance Status Matrix

| Component / Area | Status | Next Milestone / Dependency |
|---|---|---|
| **Backend Core** | Done, on `main` | Auth (JWKS ES256/RS256), documents, S3 presigned storage, findings, lawyer queue. |
| **Authentication Posture** | **Hardened (Live)** | Legacy keys disabled; publishable key verified across live sign-in and E2E runs. |
| **Database** | Live & healthy | 21 migrations live. Migrations 20 & 22 queued for deploy window. |
| **Review Agent (R1–R11)** | Complete in code | Demo mode 100% operational; Strict mode fails safe pending advocate sign-offs. |
| **Blockers Branch** | `blockers-prep` (`08acbce`) | 18 commits ahead of `main`; PR ready for review and merge. |
| **Test Suite** | **994 passed, 38 skipped, 0 failed** | Zero failures permitted; full suite green in 12.40s. |
| **Advocate Review Pack** | Prepared & guarded | `advocate_review_pack.csv` ready; atomic `apply_advocate_review.py` guarded. |
| **Human Actions Matrix** | Fully mapped | Tracked in `docs/HUMAN_ACTIONS.md` across Advocate, Tejaswi, Arjun, Poornaa, Compliance, Counsel. |

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

## 3. Remaining Works by Owner

Every engineering blocker that can be resolved in code has been completed. The remaining tasks are strictly human legal decisions, cross-team plumbing, and live deployment operations:

### A. Tejaswi (Lead / Deployments)
1. **Morning Log Review (Mon 9 Nov)**:
   - Verify journal logs following overnight run with legacy keys disabled.
2. **Deploy Migrations**:
   - Apply Migration 20 (idempotent constraint fix).
   - Apply Migration 22 ([`22_statutes_verified_guard.sql`](file:///Users/manojmj/Agentclause/supabase/migrations/20261105100000_22_statutes_verified_guard.sql) trigger).
3. **Merge Pull Request**:
   - Review and merge branch `blockers-prep` into `main` ([PR Link](https://github.com/mmanoj770/Agentclause/pull/new/blockers-prep)).
4. **Merge C9 Chat Endpoint**:
   - Merge `origin/tejaswi` to connect the real conversational chat endpoint after deploy window.
5. **Permanent Key Revocation**:
   - Execute permanent revocation of legacy keys in Supabase dashboard 24–48 hours post-disable (Tue 10 Nov).

### B. Advocate (Legal Counsel)
1. **Statutory Quote Verification (`HA-01`)**:
   - Review 7 seed statutory quotes in [`docs/advocate_review_pack.csv`](file:///Users/manojmj/Agentclause/docs/advocate_review_pack.csv) against official India Code URLs.
   - Run `python scripts/apply_advocate_review.py --apply` to atomically promote verified quotes.
2. **NDA Required Clauses Sign-off (`HA-02`)**:
   - Verify and sign off on [`nda_required_clauses.json`](file:///Users/manojmj/Agentclause/backend/app/rules/config/nda_required_clauses.json) to unblock strict mode R3 evaluation.

### C. Compliance & DPO
1. **DPDP Section 16 Data Transit Review (`HA-03`)**:
   - Sign off on Google Cloud Gemini enterprise DPA terms, global data transit disclosure, and customer upload consent language in [`docs/dpdp_intake_note.md`](file:///Users/manojmj/Agentclause/docs/dpdp_intake_note.md).

### D. Arjun (Citation Gate & Statutes DB)
1. **Database-Backed Citation Gate (`HA-04`)**:
   - In `backend/app/agents/citation_gate.py`, replace `StubFixtureCorpus` lookup with live database querying against `public.statutes` using [`section_matches()`](file:///Users/manojmj/Agentclause/backend/app/statutes/normalizer.py) from `app.statutes`.
2. **Citation Extraction & Case-Law Index (`HA-05`)**:
   - Extract `(act, section)` tokens from finding descriptions and connect case-law precedent lookups.

### E. Poornaa (Drafting Agent)
1. **Clause Manifest Schema (`HA-06`)**:
   - Deliver structured clause manifest schema for contract versions so R6 consistency and R7 asymmetry findings pass write-time citation screening.

### F. Partner Counsel (Calibration)
1. **Triage Severity Weights (`HA-07`)**:
   - Calibrate severity weights in [`backend/app/pipeline/config/triage.json`](file:///Users/manojmj/Agentclause/backend/app/pipeline/config/triage.json) to replace `status: "PLACEHOLDER"`.
2. **Asymmetry Provision Baselines (`HA-08`)**:
   - Calibrate market baselines in [`backend/app/pipeline/config/asymmetry.json`](file:///Users/manojmj/Agentclause/backend/app/pipeline/config/asymmetry.json) to replace `status: "PLACEHOLDER"`.

### G. Engineering / Manoj
1. **Test Document Cleanup**:
   - Purge the 3 test documents created during tonight's window:
     - `cd8387e9-10a3-4aa5-a98f-123779109df6`
     - `26df2e7b-1128-461b-acd6-1ceaf24bb65b`
     - `f009e905-ac8e-471d-9b2f-ae5ab1f298fb`
2. **Deprecate Finding `id` Alias (`HA-11`) - COMPLETE**:
   - Permanently removed `id` property from `_FindingId` in `backend/app/findings/schemas.py` and dropped `ID_ALIAS_UNTIL` per Tejaswi's directive (merged from `origin/arjun-alias`, `eec4e08`). Tests updated to require `finding_id` only.

---

## 4. Verification and Pull Request

- **PR Branch**: `blockers-prep`
- **PR URL**: `https://github.com/mmanoj770/Agentclause/pull/new/blockers-prep`
- **Commits Ahead of Main**: 18 commits
- **Test Suite Verification**:
  ```bash
  cd backend && PYTHONPATH=. .venv/bin/pytest -q tests
  # 994 passed, 38 skipped, 0 failed in 12.40s
  ```
