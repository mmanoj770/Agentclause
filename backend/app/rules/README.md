# Rules: Rule Engine (R4) and Completeness checker (R3)

```python
from app.rules.api import run_review

result = await run_review(contract_text, "nda", effective_date=doc.effective_date)   # strict by default
result.findings          # list[ReviewFinding], most severe first
result.skipped_rules     # every rule that did not run, and why
result.evaluation_date   # the date whose rule versions were applied
```

Or over HTTP, with a logged-in user's token: `POST /reviews` with `{"contract_text": "...", "contract_type_id": "nda"}`, plus `"effective_date": "YYYY-MM-DD"` when it is known.

`run_review` runs the version in force on the [evaluation date](#evaluation-date) of every rule whose `applies_to` includes the contract type. It also runs the completeness checker for that type (NDA only for now). When a rule and the completeness checker report the same missing clause, only the rule's finding is kept. They share the rule ID, e.g. `NDA_GOVERNING_LAW_MISSING`: the rule finding records `NDA_GOVERNING_LAW_MISSING@1`, the completeness finding `NDA_GOVERNING_LAW_MISSING`.

## Verification and severity

Every shipped rule, and the NDA completeness config, is `unverified`. Until a lawyer verifies a rule:

- strict mode skips it entirely. `run_review` and `RuleLoader` are strict by default, and so is `POST /reviews`. Strict mode also skips an unverified completeness config;
- with `strict=False` (demo and testing only) it runs, and its findings are capped at **LOW**, whatever severity the file says.

Every finding `run_review` returns carries `verification_status` from the rule or config that raised it. That field is not a `findings` column, so `to_insert_row()` leaves it out.

`POST /reviews` (add `?strict=false` for demo mode) returns:

```json
{"strict_mode": true, "status": "ok", "notice": null, "evaluation_date": "2026-10-28",
 "findings": [...],
 "skipped_rules": {"count": 1, "rules": [{"rule_id": "ICA_S27_RESTRAINT_OF_TRADE", "version": 1,
                                          "reason": "unverified_in_strict_mode"}]}}
```

A date error in the rule files (see [Gaps](#gaps)) is a 500 that names the rule, never a quiet review.

| `status` | When |
|---|---|
| `ok` | strict, and verified rules raised findings |
| `no_verified_rules_matched` | strict, and nothing verified fired. Still a 200 with `findings: []`. While every rule is unverified, this is the only strict answer |
| `demo_includes_unverified` | `strict=false`. `notice` is set; show it wherever these findings appear |

## Rule files

One JSON object per file in `rules/`. Any malformed file stops loading with an error that names the file.

| Field | Meaning |
|---|---|
| `rule_id` | `UPPER_SNAKE_CASE`; with the version it becomes the finding's `rule_applied`, e.g. `ICA_S27_RESTRAINT_OF_TRADE@1` |
| `version` | Required. A whole number starting at `1`. See [Versions](#versions) |
| `statute` | The Act with its year (`"Indian Contract Act, 1872"`), or `"Internal"` for a house baseline no statute backs |
| `section` | A section number (`"27"`, `"73(1)"`) for a statute; a short label for `Internal` |
| `applies_to` | `contract_types` codes, e.g. `["nda"]` |
| `condition` | `missing_clause('<clause id>')` or `contains_text('<phrase>', ...)` |
| `severity` | `critical`, `high`, `medium` or `low` |
| `description` | Optional. What the finding says; generated from the condition if omitted |
| `remedy_suggested` | What to change |
| `effective_from` | `YYYY-MM-DD`; the first day this version is in force |
| `effective_to` | Optional. `YYYY-MM-DD`; the last day it is in force (inclusive). Omit for open-ended |
| `superseded_by` | Optional. `RULE_ID` or `RULE_ID@<version>` of the rule that replaces this one; must be a loaded rule |
| `verification_status` | `verified` or `unverified` |

The finding's citation is built from `statute` and `section`, shaped to pass migration 18's checks:
- `"Indian Contract Act, 1872, s. 27"` is classified STATUTORY;
- `"Internal: <section>"` is classified INTERNAL_BASELINE.

That's why a statute needs its year and a real section number. A label like "General practice" is rejected unless the statute is `Internal`.

## Versions

A rule never changes in place once it has produced findings: a stored finding must still point to the wording that raised it.

- **To change a rule**, add a new file with the same `rule_id` and the next `version`. Set the old version's `effective_to` to the day before the new version's `effective_from`. Keep the old file.
- For each `rule_id`, the loader keeps **the version in force on the [evaluation date](#evaluation-date)**.
- **Loading fails, naming the file,** when:
  - two versions of one `rule_id` share a day (both ends are inclusive, and an open `effective_to` runs forever);
  - a version number appears twice;
  - `version` is missing or isn't a whole number of at least 1;
  - `superseded_by` names a rule or version that isn't loaded.
- **Strict mode applies after the date pick.** If the version in force is unverified, strict mode runs nothing for that rule. It does not fall back to an older verified version.
- `superseded_by` is a pointer for people. Use it when a rule is replaced by one with a *different* `rule_id`. The loader checks that the target exists, but dates alone decide what runs.
- Findings record the version as `rule_applied = "<rule_id>@<version>"`. `findings.rule_applied` is a plain text column, so this needs no migration. `base_rule_id()` strips the suffix.
- The completeness config is not versioned yet. Its findings use the bare ID.

### Evaluation date

Rule versions are picked for one date, in this order:

1. `on=` if the caller passes it (`run_review(..., on=date)`, `RuleLoader(..., on=date)`);
2. otherwise the contract's effective date if known: pass `effective_date=` (from `NormalizedDocument.effective_date`) to `run_review`, or `"effective_date"` in the `POST /reviews` body;
3. otherwise **today in India (Asia/Kolkata)**, not the server's clock zone. At 01:30 IST on 28 October a UTC server still says 27 October; the rules use 28 October.

The response's `evaluation_date` says which date was used. The time zone loads when the app starts: a host with no time-zone database fails at startup instead of using the wrong day.

### Gaps

For the evaluation date, each `rule_id` falls in exactly one case:

| Case | Result |
|---|---|
| A version is in force | It runs (in strict mode, only if verified) |
| The date is before the first version's `effective_from` | Skipped as `not_yet_in_force`: the rule didn't exist yet |
| The date is after the last version's `effective_to` | Skipped as `no_longer_in_force`: the rule was retired |
| The date is between one version's `effective_to` and the next one's `effective_from` | **`RuleGapError`**, naming the rule, the date and both versions. A gap is a mistake in the files, so the whole review fails rather than run with the rule silently missing. The error is logged at ERROR level before it is raised |

A gap can't reach a review unnoticed: `test_shipped_rule_files_have_no_gaps` runs `RuleLoader.gaps()`, which checks every pair of consecutive versions whatever the date, and fails as soon as an edit leaves a day uncovered. When you end a version, the next one must start on the following day.

### Skipped rules

`skipped_rules` lists everything that did not run, as `{rule_id, version, reason}`:

| `reason` | Meaning |
|---|---|
| `unverified_in_strict_mode` | The version in force (or the completeness config) is unverified |
| `not_yet_in_force` / `no_longer_in_force` | See [Gaps](#gaps) |
| `not_applicable_to_contract_type` | The rule's `applies_to` doesn't include this contract type. This reason wins over the others |

Completeness checks skipped in strict mode have `version: null`, because the completeness config is not versioned. Each review also logs one line with the counts per reason, the contract type, the mode and the date. It never logs contract text.

## Conditions

- `missing_clause('<id>')` fires when none of that clause's patterns in `clauses.py` appear. Clause IDs: `governing-law`, `confidentiality`, `confidential-info-definition`, `obligations`, `exclusions`, `term`, `return-destruction`, `residuals`.
- `contains_text('a', 'b', ...)` fires when **any** of the phrases appears (case- and whitespace-insensitive). The finding points at the nearest clause number above the match.

Matching is keyword-based and will miss unusual wording. Treat a clean result as "nothing obvious", not "compliant".

## Completeness config

`config/nda_required_clauses.json` lists the clauses an NDA must have, each with its severity once verified.
