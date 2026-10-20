"""Clause registry: how to tell whether a clause is present in contract text.

Shared by missing_clause() rules and the completeness checker, so both agree on what "present" means.
Matching is keyword/regex over normalised text (lower case, single spaces). It is deliberately simple
and will miss unusual wording; it is not a substitute for reading the contract.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Clause:
    label: str
    patterns: tuple[str, ...]

    def present_in(self, normalised_text: str) -> bool:
        return any(re.search(p, normalised_text) for p in self.patterns)


CLAUSES: dict[str, Clause] = {
    "governing-law": Clause("Governing law", (
        r"\bgoverning law\b",
        r"\bgoverned by\b.{0,40}\blaws?\b",
        r"\bconstrued in accordance with\b.{0,40}\blaws?\b",
    )),
    "confidentiality": Clause("Confidentiality obligation", (
        r"\bconfidentiality\b",
        r"\b(keep|hold|maintain|treat)\b.{0,60}\b(confidential|in confidence)\b",
    )),
    "confidential-info-definition": Clause("Definition of Confidential Information", (
        r"\bconfidential information\"?\s*(means|shall mean|includes|refers to|is defined as)\b",
        r"\bdefinition of confidential information\b",
    )),
    "obligations": Clause("Obligations of the receiving party", (
        r"\bobligations? of (the )?(receiving|recipient) party\b",
        r"\b(receiving party|recipient) (shall|agrees to|undertakes to)\b",
        r"\bshall not (disclose|use)\b",
    )),
    "exclusions": Clause("Exclusions from Confidential Information", (
        r"\bexclusions?\b",
        r"\bshall not (include|apply to)\b",
        r"\bdoes not include\b",
        r"\b(publicly available|public domain)\b",
    )),
    "term": Clause("Term", (
        r"\bterm of this agreement\b",
        r"\bfor a (period|term) of\b",
        r"\bremain in (full )?(force|effect)\b",
        r"\bshall survive\b",
    )),
    "return-destruction": Clause("Return or destruction of information", (
        r"\breturn\b.{0,80}\b(destroy|destruction)\b",
        r"\b(destroy|destruction)\b.{0,80}\breturn\b",
    )),
    "residuals": Clause("Residuals", (
        r"\bresiduals?\b",
    )),
}


def normalise(text: str) -> str:
    """Lower-case and collapse whitespace so patterns match across line breaks."""
    return re.sub(r"\s+", " ", text).strip().lower()
