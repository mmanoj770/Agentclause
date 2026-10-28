# Rules: Rule Engine (R4) and Completeness checker (R3)

```python
from app.rules.api import run_review

findings = await run_review(contract_text, "nda")   # list[ReviewFinding], most severe first; strict
```

Or over HTTP, with a logged-in user's token: `POST /reviews` with `{"contract_text": "...", "contract_type_id": "nda"}`.

`run_review` runs every rule whose `applies_to` includes the contract type, plus the completeness checker for that type (NDA only for now). When a rule and the completeness checker report the same missing clause, only the rule's finding is kept. They share the rule ID, e.g. `NDA_GOVERNING_LAW_MISSING`.

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
| `rule_id` | `UPPER_SNAKE_CASE`; becomes the finding's `rule_applied` |
| `statute` | The Act with its year (`"Indian Contract Act, 1872"`), or `"Internal"` for a house baseline no statute backs |
| `section` | A section number (`"27"`, `"73(1)"`) for a statute; a short label for `Internal` |
| `applies_to` | `contract_types` codes, e.g. `["nda"]` |
| `condition` | `missing_clause('<clause id>')` or `contains_text('<phrase>', ...)` |
| `severity` | `critical`, `high`, `medium` or `low` |
| `description` | Optional. What the finding says; generated from the condition if omitted |
| `remedy_suggested` | What to change |
| `effective_from` | `YYYY-MM-DD`; the rule is skipped before this date |
| `verification_status` | `verified` or `unverified` |

The finding's citation is built from `statute` and `section`, shaped to pass migration 18's checks:
- `"Indian Contract Act, 1872, s. 27"` is classified STATUTORY;
- `"Internal: <section>"` is classified INTERNAL_BASELINE.

That's why a statute needs its year and a real section number. A label like "General practice" is rejected unless the statute is `Internal`.

## Conditions

- `missing_clause('<id>')` fires when none of that clause's patterns in `clauses.py` appear. Clause IDs: `governing-law`, `confidentiality`, `confidential-info-definition`, `obligations`, `exclusions`, `term`, `return-destruction`, `residuals`.
- `contains_text('a', 'b', ...)` fires when **any** of the phrases appears (case- and whitespace-insensitive). The finding points at the nearest clause number above the match.

Matching is keyword-based and will miss unusual wording. Treat a clean result as "nothing obvious", not "compliant".

## Completeness config

`config/nda_required_clauses.json` lists the clauses an NDA must have, each with its severity once verified.
