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

## 3. Deprecation of Finding `id` Alias

1. **`id` Alias Removal**:
   - Per Tejaswi's directive to remove rather than extend, the deprecated `id` alias and `ID_ALIAS_UNTIL` have been completely removed from `backend/app/findings/schemas.py` (merged from `origin/arjun-alias`, commit `eec4e08`).
   - All response schemas now identify findings strictly by `finding_id`.
   - All tests have been updated and verified green.

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
- Task 8: Finding `id` alias removal per Tejaswi's directive (merged from `origin/arjun-alias`, `eec4e08`).
- Task 9: Human actions tracking table and outreach packs.
