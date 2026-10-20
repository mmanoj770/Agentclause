"""Rule Engine (R4): evaluates rules against a contract's normalised text and returns Findings."""
import re
from datetime import date

from app.rules.clauses import CLAUSES, normalise
from app.rules.schema import INTERNAL, Rule, parse_condition
from app.schemas.finding import Finding, Layer, Severity

MAX_CLAUSE_REFERENCE = 200
# A clause number at the start of a line: "7.", "7.2", "12)", "Clause 7".
_CLAUSE_NUMBER = re.compile(r"^\s*(?:clause\s+)?(\d+(?:\.\d+)*)[.)]?\s", re.IGNORECASE | re.MULTILINE)


def finding_severity(severity: Severity, verified: bool) -> Severity:
    """Unverified rules may not raise anything above LOW: nobody has checked them yet."""
    return severity if verified else Severity.LOW


def locate(text: str, position: int) -> str:
    """Clause reference for a match: the nearest clause number above it, else a short excerpt."""
    numbers = [m.group(1) for m in _CLAUSE_NUMBER.finditer(text, 0, position)]
    if numbers:
        return f"Clause {numbers[-1]}"
    excerpt = re.sub(r"\s+", " ", text[max(0, position - 40):position + 80]).strip()
    return f"Text: \"{excerpt}\""[:MAX_CLAUSE_REFERENCE]


class RuleEvaluator:
    """Runs a set of rules against one contract."""

    def __init__(self, rules: list[Rule], today: date | None = None):
        self.rules = rules
        self.today = today or date.today()

    def evaluate(self, text: str, contract_type: str) -> list[Finding]:
        contract_type = contract_type.strip().lower()
        normalised = normalise(text)
        findings = []
        for rule in self.rules:
            if contract_type not in rule.applies_to or rule.effective_from > self.today:
                continue
            clause_reference = self._fires(rule, text, normalised)
            if clause_reference is not None:
                findings.append(self._finding(rule, clause_reference))
        return findings

    @staticmethod
    def _fires(rule: Rule, text: str, normalised: str) -> str | None:
        """Return the clause reference if the rule fires, else None."""
        name, args = parse_condition(rule.condition)
        if name == "missing_clause":
            return None if CLAUSES[args[0]].present_in(normalised) else "Missing"
        # contains_text: fires if ANY phrase appears (case-insensitive, whitespace-insensitive).
        for phrase in args:
            pattern = r"\s+".join(map(re.escape, phrase.split()))
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return locate(text, m.start())
        return None

    @staticmethod
    def _finding(rule: Rule, clause_reference: str) -> Finding:
        name, args = parse_condition(rule.condition)
        if rule.description:
            description = rule.description
        elif name == "missing_clause":
            description = f"The contract has no {CLAUSES[args[0]].label.lower()} clause."
        else:
            description = f"The contract contains wording that rule {rule.rule_id} flags."
        return Finding(
            layer=Layer.COMPLETENESS if rule.statute == INTERNAL else Layer.STATUTORY,
            severity=finding_severity(rule.severity, rule.verified),
            clause_reference=clause_reference,
            description=description,
            rule_applied=rule.rule_id,
            remedy_suggested=rule.remedy_suggested,
            citation=rule.citation,
            citation_type=rule.citation_type,
        )
