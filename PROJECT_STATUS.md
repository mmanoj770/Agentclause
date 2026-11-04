# AgentClause: project status (backend and Review Agent)

Status as of 4 November 2026. Checked against `origin/main` (`41fbc94`), branch `blockers-prep` (`ae9116b`), the pushed remote branches, and read-only preflight queries on the live Supabase project (`pmrkwctwjqhrhkwtjrbz`, ap-south-1).

## Summary

- **Review Agent layers (R1–R11) and R10 pipeline are merged into `main` (`e326e29`, `a465184`, `41fbc94`).**
- **All 5 engineering blockers are solved on branch `blockers-prep` (`ae9116b`), pushed and awaiting PR merge:**
  1. Strict mode coverage metrics (`review_status`: `no_rules_verified` / `partial_unverified_rules` / `complete`) propagated to API and audit logs.
  2. Org-name normalization and conservative fuzzy disambiguation for R7 asymmetry.
  3. Pre-call DPDP PII redaction for Gemini intake (R2) and `docs/dpdp_intake_note.md`.
  4. Advocate review pack generator (`docs/advocate_review_pack.md` & `.csv`) and unrun application script (`scripts/apply_advocate_review.py`).
  5. Public contract benchmark set (`backend/tests/fixtures/public_contracts/`) and runner (`scripts/benchmark_public_contracts.py`).
- **Database: 21 migrations applied and verified on live.** Migration 21 (`public.statutes`) preflight passed 4/4 on Supabase live.
- **Backend test suite is 100% green: 957 passed, 37 skipped, 0 failed** (access test skips only).
- **Zero premature verifications:** All legal rules and configs remain strictly `unverified` pending advocate sign-off.

| Area | State |
|---|---|
| Backend foundation (auth, documents, storage, findings, queue, audit) | Done, on `main` |
| Database | Live and healthy; all 21 migrations applied (`statutes` table live) |
| Review Agent pipeline (R1–R11) | Merged to `main` (`pipeline-r10` + Gemini intake R2) |
| Blocker resolutions (`blockers-prep`) | 5 tasks committed, tested, and pushed (`ae9116b`); PR ready |
| Tests on `blockers-prep` | **957 passed, 37 skipped, 0 failed** |
| Live end-to-end run (`dry_run.py`) | Ready for deployment window (19:00–20:00) |
| Advocate-verified legal content | Review pack and apply script prepared; awaiting human review |

---

## 1. What AgentClause is

AgentClause is an AI-assisted contract review and drafting platform for Indian startups. AI agents draft, review, and explain contracts, and **a licensed Indian advocate verifies and signs off before anything is delivered**. It is designed to fail closed: an unverified rule produces no findings in strict mode, an unindexed statute or missing baseline is blocked by the citation gate, and no customer document transitions to `delivered` without human lawyer adjudication.

**Three Agents:**

| Agent | Scope | State |
|---|---|---|
| **Review Agent (R1–R11)** | Review contract, detect missing clauses, check Indian statutory compliance, score risk asymmetry, gate citations, triage risk tier | Merged on `main`; blockers resolved on `blockers-prep` |
| **Drafting Agent (D1–D8)** | Assemble drafts from verified clause library | Code on `main`; `/draft` returns fixtures; awaiting Poornaa's clause manifest (R8 #7) |
| **Conversational Agent (C1–C9)** | Answer post-review questions about settled contracts | C1–C8 on `main`; C9 chat endpoint in progress with Tejaswi (`origin/tejaswi`) |

**Document State Machine:**
```
drafted -> under_ai_review -> pending_lawyer_review -> lawyer_commented -> revision_in_progress -> under_ai_review ...
                                                    -> lawyer_approved  -> delivered
```

---

## 2. Backend & Database Status

### Applied Migrations (All 21 Live)
- Migrations 01 through 20 are clean on live.
- **Migration 21 (`20261104100000_21_statutes.sql`)**:
  - Creates `public.statutes` table: `id`, `act`, `section`, `heading`, `statute_text`, `source_url`, `effective_from`, `effective_to`, `status` (`staging` / `verified`), `created_at`, `updated_at`.
  - Indexes: unique `(act, section, effective_from)`, `act`, `status`.
  - Preflight verification (`scripts/preflight_21.sql`): **4 PASS, 0 FAIL** on live Supabase instance.
  - Normalized statute loader (`scripts/load_statutes.py`) and verification tool (`scripts/verify_statute.py`) implemented.

### Server Lifecycle & Crash Recovery
- Added `recover_stale_reviews()` in `app/main.py` lifespan: any documents orphaned in `under_ai_review` across server process restarts automatically revert to their prior state with an `ai_review_failed` audit row (`ServerProcessRestarted`).
- Timeout on database pool acquisition during test lifespan startup prevents hangs when tests run without active Postgres.

---

## 3. Review Agent (R1–R11 Layer Breakdown)

| Layer | Component | Status | Details |
|---|---|---|---|
| **R1** | Finding Schema | **Done** | `app/schemas/finding.py` defines universal finding contract across all 10 layers. |
| **R2** | Intake & Normalisation | **Done** | Gemini intake merged to `main`. On `blockers-prep`: added client-side DPDP PII redaction (PAN, Aadhaar, phone, email, bank/IFSC, GST) before API calls, with local mapping and character-for-character verbatim substring verification against original contract text. |
| **R3** | Completeness Checker | **Done (Code)** | Shipped configs for **NDA**, **Vendor/Supplier**, **Founders' Agreement**, and **SHA**. Implemented `check_with_coverage()` reporting `rules_total`, `rules_evaluated`, `rules_skipped_unverified`, and `review_status`. |
| **R4** | Rule Engine | **Done** | Evaluates date-versioned rules against normalized text, Indian date handling, clause references, and `evaluate_with_coverage()`. |
| **R5** | Statutory Rules Content | **Done (Code)** | 7 seed rules staged (ICA ss. 27, 28, 74; MSMEDA ss. 15, 16; Internal NDA baselines). All staged as `unverified` (strict mode returns explicit `no_rules_verified` status until advocate sign-off). |
| **R6** | Cross-Clause Consistency | **Done (Code)** | Conflicting facts/periods detection across clauses. Severities capped at `low` while config is placeholder. |
| **R7** | Risk Asymmetry | **Done (Code)** | Upgraded on `blockers-prep`: robust `normalize_org_name()` (casefold, M/s, honorifics, &, punctuation, Pvt/Ltd/LLP canonicalization), and conservative fuzzy matching with logging. Ambiguous matches return `None` (unknown side). |
| **R8** | Citation Gate | **In Progress** | Format alignment complete. `public.statutes` table created and seeded on DB (Migration 21). Arjun completing tasks 4–6 (DB corpus query, citation extraction, case-law index). Poornaa to provide clause manifest (R8 #7). |
| **R9** | Risk Triage | **Done (Code)** | Computes document `triage_tier` (`standard`, `enhanced`, `specialist`) and saves to `documents.triage_tier`. Lawyer queue service supports `sort_by=triage_tier`. |
| **R10** | Pipeline Orchestrator | **Done** | Async 202 background runner (`runner.py`), transaction rollbacks on failure, audit log details recording layer timings, count, and coverage metrics. |
| **R11** | Evaluation & Benchmarks | **Done** | Synthetic fixtures in `backend/tests/fixtures/contracts/` (finds 6/6 in demo mode). New public benchmark set in `backend/tests/fixtures/public_contracts/` with runner `scripts/benchmark_public_contracts.py`. |

---

## 4. What Remains by Owner

### A. Code & Merges
1. **Merge `blockers-prep` into `main`** (Manoj / Tejaswi):
   - PR URL: `https://github.com/mmanoj770/Agentclause/pull/new/blockers-prep`
   - Incorporates all 5 blocker tasks (+44 passing tests, 957 total).
2. **PR #10 (Arjun)**:
   - Fallback log sanitization to log only codes and citation hashes, never contract text.
3. **C9 Chat Endpoint (Tejaswi)**:
   - Merge `origin/tejaswi` after deployment window to connect real `/chat` route.

### B. Human & Legal Sign-offs (Prepared & Turnkey)
1. **Advocate Verification (R3 + R5)**:
   - Advocate reviews `docs/advocate_review_pack.md` and verifies quotes against India Code URLs.
   - Marks verified rows in `docs/advocate_review_pack.csv`.
   - Run `python3 scripts/apply_advocate_review.py` (do not run until advocate signs off).
2. **DPDP Compliance Review (R2)**:
   - Compliance counsel reviews `docs/dpdp_intake_note.md` regarding Google Gemini DPA terms, user consent notices (DPDP ss. 5 & 6), and Section 16 data residency.
3. **Market Baseline & Triage Calibration (R7 + R9)**:
   - Replace placeholder weights in `app/pipeline/config/asymmetry.json` and `app/pipeline/config/triage.json` once pilot feedback is gathered.

### C. Plumbing & Agent Integrations
1. **Clause Manifest (Poornaa - D1–D8, R8 #7)**:
   - Drafting agent to emit clause manifest so citation gate allows R6 and R7 findings in strict mode without blocking.
2. **Statutes DB Corpus Wiring (Arjun - R8 #4–#6)**:
   - Connect citation gate to query the live `statutes` table instead of stub dictionaries.
   - Implement citation text extraction and case-law index.

### D. Operations & Live Deployment
1. **Deployment Window (19:00–20:00)**:
   - Set live server environment variables (`S3_BUCKET`, `GEMINI_API_KEY`).
   - Run `scripts/e2e_upload.py` and `scripts/dry_run.py` to verify real S3 and database transactions.
2. **Key Rotation Schedule**:
   - Database and JWT secrets rotated.
   - IAM user and keys deleted on 2 Nov.
   - Legacy Supabase keys scheduled for disable on Friday 6 Nov (19:00) and revoke on Mon 9 Nov.
