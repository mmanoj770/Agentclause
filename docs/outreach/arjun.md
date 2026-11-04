# Outreach: Arjun (Citation Gate & Statutes DB Integration)

**Target Audience**: Arjun  
**Subject**: Statute Matching Specification, DB Trigger Guards, and Citation Gate Integration (R8 #2–6)  
**Related Artifacts**:
- Matching Rules: `docs/statutes_matching_rule.md`
- Normalizer & Matcher: `backend/app/statutes/normalizer.py`
- Trigger Guard Migration: `supabase/migrations/20261105100000_22_statutes_verified_guard.sql`
- Preflight Script: `scripts/preflight_22.sql`

---

## 1. Summary of Completed Infrastructure

To unblock the Citation Gate (Layer 8) database wiring, the following shared components have been implemented, tested, and documented:

1. **Section Matching Specification (`section_matches`)**:
   - Implemented in `backend/app/statutes/normalizer.py`:
     `section_matches(citation: str, stored: str) -> SectionMatchResult(matches: bool, match_level: str | None)`
   - Supports 3 match levels:
     - `'exact'`: `27` == `27`, `27(1)` == `27(1)`
     - `'subsection'`: citation `27` matches stored `27(1)`, `27(a)`
     - `'parent'`: citation `27(1)` matches stored base section `27`
   - Strictly blocks false positives: `27` does NOT match `270` or `27A`; `27(1)` does NOT match `27(2)`.
   - Comprehensive documentation is available at [docs/statutes_matching_rule.md](file:///Users/manojmj/Agentclause/docs/statutes_matching_rule.md).

2. **Trigger-Guarded DB Migration 22**:
   - `20261105100000_22_statutes_verified_guard.sql` defines the `statutes_verified_guard` trigger on `public.statutes`.
   - Ensures that any manual text update to a `verified` quote immediately demotes it to `staging` and clears verification evidence unless re-certified with advocate credentials.
   - Ready for review; will be deployed following migration 21.

3. **Statute Verification Tooling**:
   - `scripts/verify_statute.py` now enforces mandatory `--advocate` and `--verification-ref`, and records both the active operator and the advocate in `write_audit`.
   - `scripts/load_statutes.py` implements per-row SHA-256 hash comparison, detects drift, refuses to overwrite verified rows, and requires `--update-staging` to update staging entries.

---

## 2. Next Actions for Arjun

1. **Wire Citation Gate to `public.statutes` (R8 #4)**:
   - In `backend/app/agents/citation_gate.py`, replace `StubFixtureCorpus` lookup with live database querying against `public.statutes` where `status = 'verified'`.
   - Use `section_matches()` to evaluate whether extracted citations match candidate stored rows.
2. **Citation Extraction from Findings (R8 #5)**:
   - Extract `(act, section)` tuples from finding descriptions/citations before querying `public.statutes`.
3. **Case-Law Index (R8 #6)**:
   - Integrate case-law precedent citations once statutory gate wiring is verified.
