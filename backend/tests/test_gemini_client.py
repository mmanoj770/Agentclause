"""Gemini client: request shape, retries, validation. No real network calls."""

import json
import math

import httpx
import pytest

from app import gemini
from app.gemini import GeminiError, embed_text, generate_json


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(gemini.settings, "gemini_embedding_model", "gemini-embedding-001")
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    log = {"requests": [], "responses": []}

    def fake_post(url, headers, json, timeout):
        log["requests"].append({"url": url, "headers": headers, "json": json})
        r = log["responses"].pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(gemini.httpx, "post", fake_post)
    return log


def test_missing_key(monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "")
    with pytest.raises(GeminiError, match="GEMINI_API_KEY"):
        embed_text("x", task="RETRIEVAL_QUERY", dim=3)


def test_embedding_request_and_normalisation(calls):
    calls["responses"].append(FakeResponse(200, {"embedding": {"values": [3.0, 4.0, 0.0]}}))
    v = embed_text("clause", task="RETRIEVAL_DOCUMENT", dim=3, title="T")
    assert v == pytest.approx([0.6, 0.8, 0.0])
    req = calls["requests"][0]
    assert req["url"].endswith("/gemini-embedding-001:embedContent")
    assert req["headers"] == {"x-goog-api-key": "test-key"}
    assert "key=" not in req["url"]
    assert req["json"]["taskType"] == "RETRIEVAL_DOCUMENT"
    assert req["json"]["outputDimensionality"] == 3 and req["json"]["title"] == "T"


def test_embedding_2_uses_prefixes(calls, monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_embedding_model", "gemini-embedding-2")
    calls["responses"].append(FakeResponse(200, {"embedding": {"values": [1.0, 0.0]}}))
    embed_text("pay terms", task="RETRIEVAL_QUERY", dim=2)
    body = calls["requests"][0]["json"]
    assert "taskType" not in body
    assert body["content"]["parts"][0]["text"] == "task: search result | query: pay terms"


def test_wrong_dimension_rejected(calls):
    calls["responses"].append(FakeResponse(200, {"embedding": {"values": [1.0, 0.0]}}))
    with pytest.raises(GeminiError, match="768"):
        embed_text("x", task="RETRIEVAL_QUERY", dim=768)


@pytest.mark.parametrize("payload", [{"nope": 1}, {"embedding": {"values": [0.0, 0.0]}},
                                     {"embedding": {"values": [math.nan, 1.0]}}])
def test_bad_embedding_payloads(calls, payload):
    calls["responses"].append(FakeResponse(200, payload))
    with pytest.raises(GeminiError):
        embed_text("x", task="RETRIEVAL_QUERY", dim=2)


def test_retries_transient_errors(calls):
    calls["responses"] += [FakeResponse(429, {"error": "rate"}),
                           httpx.ConnectTimeout("slow"),
                           FakeResponse(200, {"embedding": {"values": [1.0]}})]
    assert embed_text("x", task="RETRIEVAL_QUERY", dim=1) == [1.0]
    assert len(calls["requests"]) == 3


def test_does_not_retry_client_errors(calls):
    calls["responses"] += [FakeResponse(404, {"error": "model not found"})]
    with pytest.raises(GeminiError, match="HTTP 404"):
        embed_text("x", task="RETRIEVAL_QUERY", dim=1)
    assert len(calls["requests"]) == 1


def test_gives_up_after_retries(calls):
    calls["responses"] += [FakeResponse(503, {}) for _ in range(4)]
    with pytest.raises(GeminiError, match="HTTP 503"):
        embed_text("x", task="RETRIEVAL_QUERY", dim=1)


def _gen(text, thought=None):
    parts = ([{"text": thought, "thought": True}] if thought else []) + [{"text": text}]
    return FakeResponse(200, {"candidates": [{"content": {"parts": parts}}]})


def test_generate_json_parses_and_skips_thoughts(calls):
    calls["responses"].append(_gen('```json\n{"edits": []}\n```', thought="thinking..."))
    assert generate_json("p", system="s") == {"edits": []}
    body = calls["requests"][0]["json"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["systemInstruction"]["parts"][0]["text"] == "s"


@pytest.mark.parametrize("resp", [
    FakeResponse(200, {"promptFeedback": {"blockReason": "SAFETY"}}),
    _gen("not json"),
    _gen("[1, 2]"),
    FakeResponse(200, "<html>"),
])
def test_generate_json_bad_answers(calls, resp):
    calls["responses"].append(resp)
    with pytest.raises(GeminiError):
        generate_json("p", system="s")
