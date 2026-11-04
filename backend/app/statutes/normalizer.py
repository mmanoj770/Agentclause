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
