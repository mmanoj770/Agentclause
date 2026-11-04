# Statute Section Matching Specification

**Module**: `backend/app/statutes/normalizer.py`  
**Function**: `section_matches(citation: str, stored: str) -> SectionMatchResult`  
**Target Audience**: Citation Gate (R8 #4–6), Arjun, Rule Engine Integrations  
**Status**: Ready for wiring into Citation Gate

---

## 1. Context and Objective

When findings extracted from contracts cite statutory provisions (e.g., Section 27 of ICA, Section 15 of MSMED Act), the Citation Gate must look up the citation against the verified rows in `public.statutes`.

Because citations in contract review may cite either a base section (e.g. `Section 27`) or a specific subsection (e.g. `Section 27(1)`), and the database may store either granular subsections or parent section entries, a robust matching rule is required that:
1. Resolves valid hierarchical matches (parent <-> subsection).
2. Prevents catastrophic false positives (e.g., matching section 27 to section 270 or section 27A).
3. Preserves auditability by recording the exact match level.

---

## 2. Match Levels

The function returns a `SectionMatchResult(matches: bool, match_level: str | None)`.

### 2.1 `exact`
Citation and stored section resolve to the exact same canonical section string after normalisation.
- **Example**: `s. 27` vs `27` -> `exact`
- **Example**: `27(1)` vs `27(1)` -> `exact`
- **Example**: `s. 27 (1)(a)` vs `27(1)(a)` -> `exact`

### 2.2 `subsection`
The citation refers to the base parent section without a subsection, and the database stores a subsection of that base section.
- **Example**: Citation `27` vs Stored `27(1)` -> `subsection`
- **Example**: Citation `27` vs Stored `27(a)` -> `subsection`
- **Example**: Citation `27` vs Stored `27(1)(a)` -> `subsection`
- **Rationale**: A general citation to Section 27 is substantiated by verified text stored for any subsection of Section 27.

### 2.3 `parent`
The citation specifies a subsection, but the database only stores the parent base section.
- **Example**: Citation `27(1)` vs Stored `27` -> `parent`
- **Example**: Citation `28(a)` vs Stored `28` -> `parent`
- **Example**: Citation `s. 74(1)` vs Stored `74` -> `parent`
- **Rationale**: Acts stored as monolithic section texts (e.g. Section 74) contain all subsections within that row; a citation to a specific subsection is supported by the parent entry.

---

## 3. False Positive Protection (Strictly Rejected)

The following must **NEVER** match (`matches=False`, `match_level=None`):

| Citation | Stored | Why Rejected |
|---|---|---|
| `27` | `270` | Distinct section number; numeric prefix is not a hierarchy. |
| `27` | `27A` | Suffix letter denotes a distinct statutory section (e.g., Arbitration Act s. 29A vs 29). |
| `27A` | `27` | Suffix letter section cannot match parent base section without letter. |
| `27(1)` | `27(2)` | Sibling subsections are mutually exclusive. |
| `27(1)` | `27(10)` | Prefix match on subsection digits rejected (1 vs 10). |
| `27(a)` | `27(b)` | Sibling lettered clauses are mutually exclusive. |
| `""` | `27` | Empty or malformed citation rejected. |

---

## 4. Usage in Citation Gate (Arjun's DB Wiring)

When wiring the Citation Gate into `public.statutes`:

```python
from app.statutes.normalizer import section_matches, normalise_statute_citation

# In CitationGate lookup:
def verify_finding_citation(conn, act: str, citation_sec: str) -> bool:
    # 1. Fetch all candidate active verified rows for the act
    candidates = conn.execute(
        "select id, section from public.statutes where act = %s and status = 'verified' ...",
        (canonical_act,)
    ).fetchall()
    
    # 2. Evaluate section_matches for each candidate
    for row in candidates:
        result = section_matches(citation=citation_sec, stored=row["section"])
        if result.matches:
            # Match found (exact, subsection, or parent)
            return True
            
    return False
```

This helper guarantees consistent behavior across Python unit tests, in-memory stubs, and live database queries.
