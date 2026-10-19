import json
from pathlib import Path

from app.agents.conversational.classifier import (
    QuestionLabel,
    classify,
    matches_advice_rule,
)

DATA = Path(__file__).parent / "data" / "classifier_set.json"


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        self.calls += 1
        return self.response


class RaisingLLM:
    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        raise RuntimeError("network down")


def test_rule_hit_skips_llm():
    llm = FakeLLM('{"label": "explain"}')
    result = classify("Should I sue them?", llm)
    assert result.label == QuestionLabel.ADVISE
    assert result.source == "rule"
    assert llm.calls == 0


def test_explain_from_llm():
    result = classify("What does clause 9 mean?", FakeLLM('{"label": "explain"}'))
    assert result.label == QuestionLabel.EXPLAIN
    assert result.source == "llm"


def test_off_topic_from_llm():
    result = classify("Who won the match?", FakeLLM('{"label": "off_topic"}'))
    assert result.label == QuestionLabel.OFF_TOPIC


def test_fenced_json_parsed():
    result = classify("What is the term?", FakeLLM('```json\n{"label": "explain"}\n```'))
    assert result.label == QuestionLabel.EXPLAIN


def test_bad_json_fails_closed_to_advise():
    result = classify("What is the term?", FakeLLM("I think it is fine"))
    assert result.label == QuestionLabel.ADVISE
    assert result.source == "fallback"


def test_unknown_label_fails_closed():
    result = classify("What is the term?", FakeLLM('{"label": "maybe"}'))
    assert result.label == QuestionLabel.ADVISE
    assert result.source == "fallback"


def test_llm_error_fails_closed():
    result = classify("What is the term?", RaisingLLM())
    assert result.label == QuestionLabel.ADVISE
    assert result.source == "fallback"


def test_rules_are_case_insensitive():
    assert matches_advice_rule("SHOULD I sign?")
    assert matches_advice_rule("is my non-compete Enforceable")


def test_dataset_shape():
    items = json.loads(DATA.read_text(encoding="utf-8"))
    labels = {i["label"] for i in items}
    assert len(items) >= 60
    assert labels == {"explain", "advise", "off_topic"}
    questions = [i["q"] for i in items]
    assert len(set(questions)) == len(questions)


def test_rules_never_flag_explain_or_off_topic_questions():
    items = json.loads(DATA.read_text(encoding="utf-8"))
    wrongly_flagged = [
        i["q"] for i in items if i["label"] != "advise" and matches_advice_rule(i["q"])
    ]
    assert wrongly_flagged == []