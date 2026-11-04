"""
Thin client for the Google Gemini REST API, shared by:
  - D3 / D4: clause and query embeddings (embed_text)
  - D5:      clause adaptation (generate_json)

Design notes
- Model names live in config (settings.gemini_*_model) so they can be swapped
  without code changes. Google retires models regularly (text-embedding-004 was
  shut down on 2026-01-14), so never hard-code a model name elsewhere.
- The API key is sent in the x-goog-api-key header, not the URL, so it never
  ends up in logs or error messages.
- Every failure is raised as GeminiError with a readable message. Callers decide
  whether to fail or fall back; nothing here swallows errors silently.
- Transient failures (429 rate limit, 5xx, network) are retried with backoff.
"""

from __future__ import annotations

import json
import math
import time

import httpx

from app.config import settings

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class GeminiError(RuntimeError):
    """Any failure talking to Gemini (missing key, HTTP error, bad response)."""


def _post(model: str, method: str, body: dict, *, timeout: float, retries: int = 3) -> dict:
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not set. Add it to .env.local in the repo root.")

    url = f"{BASE_URL}/{model}:{method}"
    headers = {"x-goog-api-key": settings.gemini_api_key}
    last_error = "unknown error"

    for attempt in range(retries + 1):
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=timeout)
        except httpx.HTTPError as exc:  # timeouts, DNS, connection resets
            last_error = f"network error: {type(exc).__name__}"
        else:
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise GeminiError(f"{model}:{method} returned a non-JSON response") from exc
                if not isinstance(data, dict):
                    raise GeminiError(f"{model}:{method} returned an unexpected response shape")
                return data
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
            if response.status_code not in RETRYABLE_STATUS:
                break  # 400/401/403/404 will not fix themselves
        if attempt < retries:
            time.sleep(min(2 ** attempt, 8))

    raise GeminiError(f"Gemini {model}:{method} failed - {last_error}")


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def embed_text(text: str, *, task: str, dim: int, title: str | None = None) -> list[float]:
    """
    Return a unit-length embedding of exactly `dim` dimensions.

    task: "RETRIEVAL_DOCUMENT" for clauses being stored,
          "RETRIEVAL_QUERY"    for search queries.
    Documents and queries must use the matching task, otherwise similarity
    scores are noticeably worse.
    """
    if task not in ("RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"):
        raise ValueError(f"Unsupported embedding task: {task}")
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")

    model = settings.gemini_embedding_model
    if "embedding-2" in model:
        # gemini-embedding-2 has no task_type field; the task goes in the text.
        if task == "RETRIEVAL_QUERY":
            text = f"task: search result | query: {text}"
        else:
            text = f"title: {title or 'none'} | text: {text}"
        body = {
            "model": f"models/{model}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": dim,
        }
    else:
        body = {
            "model": f"models/{model}",
            "content": {"parts": [{"text": text}]},
            "taskType": task,
            "outputDimensionality": dim,
        }
        if title and task == "RETRIEVAL_DOCUMENT":
            body["title"] = title

    data = _post(model, "embedContent", body, timeout=30)
    try:
        values = [float(v) for v in data["embedding"]["values"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise GeminiError("Unexpected embedding response shape from Gemini") from exc

    if len(values) != dim:
        raise GeminiError(
            f"Expected a {dim}-dim vector from {model}, got {len(values)}. "
            "The database column is vector(768); do not change one without the other."
        )
    if not all(math.isfinite(v) for v in values):
        raise GeminiError("Gemini returned a vector containing NaN/Infinity")

    # Truncated gemini-embedding-001 vectors are not unit length; normalise so
    # cosine similarity behaves the same for every model.
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0:
        raise GeminiError("Gemini returned an all-zero vector")
    return [v / norm for v in values]


# ---------------------------------------------------------------------------
# Text generation (JSON mode)
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def generate_json(prompt: str, *, system: str, timeout: float = 60, model: str | None = None) -> dict:
    """Ask the generation model (or `model`, a settings value) for a JSON object and return it parsed."""
    model = model or settings.gemini_generation_model
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    data = _post(model, "generateContent", body, timeout=timeout)

    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        feedback = data.get("promptFeedback") or {}
        reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
        raise GeminiError(f"Gemini returned no answer (block reason: {reason})") from exc

    text = "".join(
        p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought")
    )
    try:
        parsed = json.loads(_strip_code_fences(text))
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise GeminiError("Gemini returned JSON that is not an object")
    return parsed
