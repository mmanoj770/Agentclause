# Outreach: Tejaswi (Release Management & Migration Sequencing)

**Target Audience**: Tejaswi  
**Subject**: Branch `blockers-prep` Verification, Migration Plan (19–22), and Deploy Gate  
**Branch**: `origin/blockers-prep`  
**PR**: Prepared, open for review (do not merge until approved)

---

## 1. Executive Summary

Branch `blockers-prep` resolves all blocker preparation tasks across layers R2 through R11 without touching any human-owned items or faking verifications.
- **Test Baseline**: **1001 passed**, 38 skipped, **0 failed** (100% green).
- **Rule Engine Integrity**: Strict mode guarantees zero verified findings when rules are unverified (`review_status == "no_rules_verified"`).
- **Hard Rules Maintained**: No `verification_status` was set to `"verified"`. No database migrations were applied. No secrets were accessed or committed.

---

## 2. Database Migration Sequencing

Per release guidelines, migrations must be executed sequentially:

| Migration | Name | Status | Deployment Pre-requisite |
|---|---|---|---|
| **19** | `19_document_chunks.sql` | Applied on live (SHA verified) | Confirmed clean by `supabase migration list`. |
| **20** | `20_...` | Pending | Must ensure idempotent form (`drop constraint if exists` before add). |
| **21** | `21_statutes.sql` | Pending | Preflight check prepared: `scripts/preflight_21.sql`. |
| **22** | `22_statutes_verified_guard.sql` | Pending (file only) | Trigger guard for verified quotes. Preflight check: `scripts/preflight_22.sql`. |

---

## 3. Date Reminders & Deprecation Guards

1. **`ID_ALIAS_UNTIL` (2026-11-15)**:
   - Added automated guard test in `backend/tests/test_finding_views.py`: `test_id_alias_7_day_expiration_guard`.
   - The test will fail in CI starting on **November 8, 2026** (7 days prior to deadline) to ensure the team removes the deprecated `id` alias property or deliberately extends the date with team alignment.
   - The date itself was not altered.

---

## 4. Prepared PR Details

The PR includes:
- Task 1: Public sample provenance cleanup (`sample_stub`).
- Task 2: Statute quote consistency test & review pack generator tracking CPC s. 20.
- Task 3: `apply_advocate_review.py` transaction safety & refusal guards.
- Task 4: Migration 22 trigger guard and `preflight_22.sql`.
- Task 5: `section_matches()` implementation & `docs/statutes_matching_rule.md`.
- Task 6: PII redaction regex hardening (currencies, dates, clause numbers, invoice IDs), retry on garbled placeholders, and DPDP scope notice.
- Task 7: Safe failure surfaces: R7 `side_unknown=True` on `side=None`, R7/R9 `provisional=True` flags, R1/R10 `review_status` schema propagation.
- Task 8: 7-day expiration guard test for `ID_ALIAS_UNTIL`.
- Task 9: Human actions tracking table and outreach packs.
