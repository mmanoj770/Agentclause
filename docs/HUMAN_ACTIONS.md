# Human Actions & External Blocker Tracking Table

**Repository**: `AgentClause`  
**Branch**: `blockers-prep`  
**Last Updated**: November 8, 2026 (Post Key-Disable Window)  
**Purpose**: Comprehensive tracking of every human-only decision, verification, and external dependency required to transition the AgentClause review agent from interim/staging to full production readiness.

---

## 1. Master Human Actions Matrix

| Item # | Owner | Task & Deliverable | Blocking Layers | Exact Next Action | Prepared Artifacts / Tools | Target Date |
| :---: | :--- | :--- | :---: | :--- | :--- | :---: |
| **HA-01** | **Advocate** (Legal Counsel) | Statutory Quote Verification (ICA ss. 27, 28, 74; MSMED Act ss. 15, 16; CPC s. 20) | **R4, R5, R8** | Review quotes against India Code and mark `VERIFIED` in review pack CSV. Run `apply_advocate_review.py --apply`. | [advocate_review_pack.csv](file:///Users/manojmj/Agentclause/docs/advocate_review_pack.csv)<br>[apply_advocate_review.py](file:///Users/manojmj/Agentclause/scripts/apply_advocate_review.py)<br>[outreach/advocate.md](file:///Users/manojmj/Agentclause/docs/outreach/advocate.md) | Prior to Pilot Launch |
| **HA-02** | **Advocate** (Legal Counsel) | Mandatory NDA Clause Baseline Verification | **R3** | Verify and sign off on required NDA clauses in `nda_required_clauses.json`. | [advocate_review_pack.md](file:///Users/manojmj/Agentclause/docs/advocate_review_pack.md) | Prior to Pilot Launch |
| **HA-03** | **Compliance / DPO** | DPDP Act 2023 Regulatory & Data Transit Review | **R2, R10** | Confirm Google Cloud enterprise DPA status, approve Section 16 cross-border transfer compliance, and approve customer consent notices. | [dpdp_intake_note.md](file:///Users/manojmj/Agentclause/docs/dpdp_intake_note.md)<br>[outreach/compliance.md](file:///Users/manojmj/Agentclause/docs/outreach/compliance.md) | Prior to Production Ingestion |
| **HA-04** | **Arjun** | Database-Backed Citation Gate Wiring (Tasks 2–4) | **R8** | Replace in-memory `StubFixtureCorpus` with SQL lookup on `public.statutes` using `section_matches()`. | [statutes_matching_rule.md](file:///Users/manojmj/Agentclause/docs/statutes_matching_rule.md)<br>[normalizer.py](file:///Users/manojmj/Agentclause/backend/app/statutes/normalizer.py)<br>[outreach/arjun.md](file:///Users/manojmj/Agentclause/docs/outreach/arjun.md) | Next Sprint |
| **HA-05** | **Arjun** | Finding Citation Extraction & Case-Law Index (Tasks 5–6) | **R8** | Extract citation tokens from finding text; integrate case-law database lookup. | [outreach/arjun.md](file:///Users/manojmj/Agentclause/docs/outreach/arjun.md) | Next Sprint |
| **HA-06** | **Poornaa** | Clause Manifest (R8 #7) & Drafting Agent Interface (D1–D8) | **R6, R7, R8** | Deliver structured clause manifest schema so R6 consistency and R7 asymmetry findings pass the gate. | [outreach/poornaa.md](file:///Users/manojmj/Agentclause/docs/outreach/poornaa.md) | Next Sprint |
| **HA-07** | **Legal Counsel** (Partner) | Calibration of Risk Triage Weights (`triage.json`) | **R9** | Calibrate severity points, asymmetry weights, and review tier thresholds; replace `status: "PLACEHOLDER"`. | [triage.json](file:///Users/manojmj/Agentclause/backend/app/pipeline/config/triage.json) | Pre-General Availability |
| **HA-08** | **Legal Counsel** (Partner) | Calibration of Risk Asymmetry Baselines (`asymmetry.json`) | **R7** | Calibrate provision weights and provide market baselines for contract types; replace `status: "PLACEHOLDER"`. | [asymmetry.json](file:///Users/manojmj/Agentclause/backend/app/pipeline/config/asymmetry.json) | Pre-General Availability |
| **HA-09** | **Tejaswi** | Migration Sequencing (20 -> 21 -> 22) | **All DB** | Confirm migration 19 clean on live; deploy 20 (idempotent), 21 (statutes), and 22 (trigger guard). | [22_statutes_verified_guard.sql](file:///Users/manojmj/Agentclause/supabase/migrations/20261105100000_22_statutes_verified_guard.sql)<br>[preflight_21.sql](file:///Users/manojmj/Agentclause/scripts/preflight_21.sql)<br>[preflight_22.sql](file:///Users/manojmj/Agentclause/scripts/preflight_22.sql) | Scheduled Deploy Window |
| **HA-10** | **Tejaswi** | Review and Merge PR `blockers-prep` | **Main Branch** | Review PR on GitHub; merge to `main` following successful deployment window. | [PR Link](https://github.com/mmanoj770/Agentclause/pull/new/blockers-prep)<br>[outreach/tejaswi.md](file:///Users/manojmj/Agentclause/docs/outreach/tejaswi.md) | Post-Deploy Window |
| **HA-11** | **Engineering Team** | Deprecation of Finding `id` Alias (`ID_ALIAS_UNTIL`) | **API Schemas** | Remove `id` property from `_FindingId` in `app/findings/schemas.py` before November 22, 2026 (`ID_ALIAS_UNTIL` extended to 22 Nov). | [test_finding_views.py](file:///Users/manojmj/Agentclause/backend/tests/test_finding_views.py) | November 15–22, 2026 |
| **HA-12** | **Engineering / Manoj** | Post-Deploy Test Document Cleanup | **Live DB** | Purge 3 test documents created during key-disable window (`cd8387e9...`, `26df2e7b...`, `f009e905...`). | Live Database Cleanup Script | November 9, 2026 |
| **HA-13** | **Tejaswi / Team** | Permanent Revocation of Legacy Keys | **Supabase API** | Permanently revoke disabled legacy keys in Supabase dashboard 24–48 hours post-disable. | Supabase Dashboard | November 10, 2026 |

---

## 2. Layer-by-Layer Blocking Status

| Layer | Component | Code Status | Human Blocker Remaining |
|---|---|---|---|
| **R2** | Intake Normalisation | Redaction & restoration hardened; regexes tuned for currencies/dates/invoices; retry on garbled placeholders active. | DPDP policy confirmation on external Gemini transmission (HA-03). |
| **R3** | Completeness Checker | Strict mode skips unverified configs with explicit `review_status="no_rules_verified"`. | Advocate verification of `nda_required_clauses.json` (HA-02). |
| **R4/R5** | Rule Engine & Statutory Rules | Strict mode refusal guards active; quote normalization and single-source-of-truth tests passing. | Advocate verification of 7 seed rules against India Code (HA-01). |
| **R6** | Cross-Clause Consistency | Engine logic functional; strict-mode severity caps active. | Poornaa's clause manifest (HA-06) to unblock gate passing. |
| **R7** | Risk Asymmetry | Normalised org matching with fuzzy fallback; `side_unknown=True` on `side=None`; provisional flag enabled. | Counsel market baselines (HA-08) & clause manifest (HA-06). |
| **R8** | Citation Gate | Database schemas (mig 21/22), trigger guards, matching logic (`section_matches`) implemented. | Arjun's DB wiring (HA-04) and extraction (HA-05). |
| **R9** | Risk Triage | Tier logic and audit trail functional; provisional flag propagated to `/queue` and responses. | Counsel weight calibration (HA-07). |
| **R10** | Pipeline Runner | Audit logging, transaction safety, layer error handling, coverage and review status propagation complete. | Live DB migration deployment (HA-09). |
| **R11** | Evaluation & Benchmarking | Public contract provenance cleaned (`sample_stub`); 3 synthetic fixtures verified in strict mode (`review_status="no_rules_verified"`). | Testing against real-world Indian contracts once non-synthetic intake is approved. |
