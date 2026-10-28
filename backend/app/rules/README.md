# Rules: Rule Engine (R4) and Completeness checker (R3)

```python
from app.rules.api import run_review

findings = await run_review(contract_text, "nda")   # list[ReviewFinding], most severe first; strict
```

Or over HTTP, with a logged-in user's token: `POST /reviews` with `{"contract_text": "...", "contract_type_id": "nda"}`.

`run_review` runs the version in force today of every rule whose `applies_to` includes the contract type. Pass `on=date(...)` to review as of another date. It also runs the completeness checker for that type (NDA only for now). When a rule and the completeness checker report the same missing clause, only the rule's finding is kept. They share the rule ID, e.g. `NDA_GOVERNING_LAW_MISSING`: the rule finding records `NDA_GOVERNING_LAW_MISSING@1`, the completeness finding `NDA_GOVERNING_LAW_MISSING`.

## Verification and severity

Every shipped rule, and the NDA completeness config, is `unverified`. Until a lawyer verifies a rule:

- strict mode skips it entirely. `run_review` and `RuleLoader` are strict by default, and so is `POST /reviews`. Strict mode also skips an unverified completeness config;
- with `strict=False` (demo and testing only) it runs, and its findings are capped at **LOW**, whatever severity the file says.

Every finding `run_review` returns carries `verification_status` from the rule or config that raised it. That field is not a `findings` column, so `to_insert_row()` leaves it out.

`POST /reviews` (add `?strict=false` for demo mode) returns:

```json
{"strict_mode": true, "status": "ok", "notice": null, "findings": [...]}
```

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
- For each `rule_id`, the loader keeps **the version in force on the evaluation date**, which defaults to today (`RuleLoader(..., on=date)`, `run_review(..., on=date)`). A date with no version in force means that rule doesn't run.
- **Loading fails, naming the file,** when:
  - two versions of one `rule_id` share a day (both ends are inclusive, and an open `effective_to` runs forever);
  - a version number appears twice;
  - `version` is missing or isn't a whole number of at least 1;
  - `superseded_by` names a rule or version that isn't loaded.
- **Strict mode applies after the date pick.** If the version in force is unverified, strict mode runs nothing for that rule. It does not fall back to an older verified version.
- `superseded_by` is a pointer for people. Use it when a rule is replaced by one with a *different* `rule_id`. The loader checks that the target exists, but dates alone decide what runs.
- Findings record the version as `rule_applied = "<rule_id>@<version>"`. `findings.rule_applied` is a plain text column, so this needs no migration. `base_rule_id()` strips the suffix.
- The completeness config is not versioned yet. Its findings use the bare ID.

## Conditions

- `missing_clause('<id>')` fires when none of that clause's patterns in `clauses.py` appear. Clause IDs: `governing-law`, `confidentiality`, `confidential-info-definition`, `obligations`, `exclusions`, `term`, `return-destruction`, `residuals`.
- `contains_text('a', 'b', ...)` fires when **any** of the phrases appears (case- and whitespace-insensitive). The finding points at the nearest clause number above the match.

Matching is keyword-based and will miss unusual wording. Treat a clean result as "nothing obvious", not "compliant".

## Completeness config

`config/nda_required_clauses.json` lists the clauses an NDA must have, each with its severity once verified.
