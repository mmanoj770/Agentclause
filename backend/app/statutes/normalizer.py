"""Normaliser and display mapping for public.statutes (R8 #3)."""
import re

# Canonical Act names mapped from common aliases and abbreviations.
# All alias keys are lowercase with whitespace collapsed.
_ACT_MAP: dict[str, str] = {
    # Indian Contract Act, 1872
    "indian contract act, 1872": "Indian Contract Act, 1872",
    "indian contract act": "Indian Contract Act, 1872",
    "contract act, 1872": "Indian Contract Act, 1872",
    "contract act": "Indian Contract Act, 1872",
    "ica": "Indian Contract Act, 1872",
    "ica, 1872": "Indian Contract Act, 1872",
    "ica 1872": "Indian Contract Act, 1872",

    # Code of Civil Procedure, 1908
    "code of civil procedure, 1908": "Code of Civil Procedure, 1908",
    "code of civil procedure": "Code of Civil Procedure, 1908",
    "cpc": "Code of Civil Procedure, 1908",
    "cpc, 1908": "Code of Civil Procedure, 1908",
    "cpc 1908": "Code of Civil Procedure, 1908",

    # Micro, Small and Medium Enterprises Development Act, 2006
    "micro, small and medium enterprises development act, 2006": "Micro, Small and Medium Enterprises Development Act, 2006",
    "micro, small and medium enterprises development act": "Micro, Small and Medium Enterprises Development Act, 2006",
    "msmed act, 2006": "Micro, Small and Medium Enterprises Development Act, 2006",
    "msmed act": "Micro, Small and Medium Enterprises Development Act, 2006",
    "msmed": "Micro, Small and Medium Enterprises Development Act, 2006",
    "msmed, 2006": "Micro, Small and Medium Enterprises Development Act, 2006",

    # Specific Relief Act, 1963
    "specific relief act, 1963": "Specific Relief Act, 1963",
    "specific relief act": "Specific Relief Act, 1963",
    "sra": "Specific Relief Act, 1963",
    "sra, 1963": "Specific Relief Act, 1963",

    # Arbitration and Conciliation Act, 1996
    "arbitration and conciliation act, 1996": "Arbitration and Conciliation Act, 1996",
    "arbitration and conciliation act": "Arbitration and Conciliation Act, 1996",
    "arbitration act": "Arbitration and Conciliation Act, 1996",
    "arbitration act, 1996": "Arbitration and Conciliation Act, 1996",

    # Companies Act, 2013
    "companies act, 2013": "Companies Act, 2013",
    "companies act": "Companies Act, 2013",
}


def normalise_act_name(act: str, year: int | None = None) -> str:
    """Resolve an Act name (or alias/abbreviation) to its canonical form.

    If year is provided and the string alone did not match, combines them: e.g. ("ICA", 1872).
    If no alias matches, returns the title-cased and whitespace-collapsed string.
    """
    cleaned = " ".join(act.strip().split())
    key = cleaned.lower()
    if key in _ACT_MAP:
        return _ACT_MAP[key]
    if year:
        with_year = f"{key}, {year}"
        if with_year in _ACT_MAP:
            return _ACT_MAP[with_year]
    return cleaned


def normalise_section_number(section: str) -> str:
    """Clean section key while preserving exact subsections.

    e.g. 's. 27' -> '27', 'Section 27' -> '27', ' 27 (1) ' -> '27(1)'.
    '27(1)', '27(a)', and '27' remain distinct and match exactly or not at all.
    """
    s = section.strip()
    s = re.sub(r"^(?:section|sec\.?|s\.)\s*", "", s, flags=re.IGNORECASE)
    # Collapse spaces around parentheses e.g. '27 (1)' -> '27(1)'
    s = re.sub(r"\s*\(\s*", "(", s)
    s = re.sub(r"\s*\)\s*", ")", s)
    return s.strip()


def normalise_statute_citation(act: str, year: int | None, section: str) -> tuple[str, str]:
    """Return (canonical_act_name, canonical_section) for gate and loader lookups."""
    return normalise_act_name(act, year), normalise_section_number(section)


from dataclasses import dataclass

@dataclass(frozen=True)
class SectionMatchResult:
    matches: bool
    match_level: str | None  # "exact", "subsection", "parent", or None


def section_matches(citation: str, stored: str) -> SectionMatchResult:
    """Evaluate whether a statute citation matches a stored database section.

    Matching Rules (R8 #4-6 / for citation_gate):
    1. 'exact': citation matches stored section exactly (e.g. '27' == '27', or '27(1)' == '27(1)').
    2. 'subsection': citation is a base section ('27') and stored section is a subsection of it ('27(1)', '27(a)', '27(1)(a)').
    3. 'parent': citation specifies a subsection ('27(1)') and stored section is its parent base section ('27').
       Used as a fallback when the database has only the parent section stored.
    4. False positives are strictly rejected: '27' does not match '270', '27A', '271'; '27(1)' does not match '27(2)'.
    """
    cit = normalise_section_number(citation)
    sto = normalise_section_number(stored)
    if not cit or not sto:
        return SectionMatchResult(matches=False, match_level=None)

    # 1. Exact match
    if cit == sto:
        return SectionMatchResult(matches=True, match_level="exact")

    # 2. Citation is base section without subsection (e.g. '27')
    # Matches any stored subsection: '27(x)', '27(1)', '27(a)'
    if "(" not in cit:
        if sto.startswith(cit + "("):
            return SectionMatchResult(matches=True, match_level="subsection")

    # 3. Citation specifies a subsection (e.g. '27(1)')
    # Matches its parent base section: '27'
    else:
        parent_cit = cit.split("(", 1)[0]
        if sto == parent_cit:
            return SectionMatchResult(matches=True, match_level="parent")

    return SectionMatchResult(matches=False, match_level=None)


def display_status(status: str) -> str:
    """Map DB verification_status enum to user/API display label.

    'staging' is displayed everywhere as 'unverified'.
    'verified' is displayed as 'verified'.
    """
    st = status.strip().lower()
    if st == "staging":
        return "unverified"
    if st == "verified":
        return "verified"
    raise ValueError(f"Unknown verification_status: {status!r}")


def normalize_statute_quote(text: str) -> str:
    """Normalize statute text for comparison between rule files and seed statutes.

    Strips rule prefix citations (e.g. 's.28: \"'), exceptions, punctuation, and collapses
    whitespace/casing to compare the core statutory quote text.
    """
    if not text:
        return ""
    # Strip rule prefix like 's.28: "' or 's.15: "'
    t = re.sub(r'^\s*s\.\s*\d+\s*:\s*["\']?', '', text)
    # Strip statutory exceptions appended to rule basis (e.g. 'Exception 1: ...')
    t = re.sub(r'["\']?\s*Exception\s*\d+.*$', '', t, flags=re.DOTALL)
    # Strip quotes
    t = re.sub(r'["\'`]', ' ', t)
    # Strip subsection markers like (a), (b), (1)
    t = re.sub(r'\([a-zA-Z0-9]+\)', ' ', t)
    # Normalize punctuation and non-alphanumeric
    t = re.sub(r'[^a-zA-Z0-9\s]', ' ', t)
    tokens = t.casefold().split()
    # Normalize minor memory drafting variant in s.28: "a contract" vs "any contract"
    # in "...liability under or in respect of a/any contract..."
    norm = []
    for tok in tokens:
        if tok == "any" and norm and norm[-1] == "of":
            norm.append("a")
        else:
            norm.append(tok)
    return " ".join(norm)

