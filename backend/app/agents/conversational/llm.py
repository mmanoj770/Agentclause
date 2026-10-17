import os
import time
from typing import Protocol

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"


class LLMClient(Protocol):
    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str: ...


class AnthropicClient:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        import anthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_CLAUDE_MODEL)

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in message.content if b.type == "text")


class GeminiClient:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        from google import genai

        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self.client = genai.Client(api_key=key)
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max(max_tokens, 2000),
            temperature=0.0,
        )
        for attempt in range(4):
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=user, config=config
                )
                return response.text or ""
            except Exception as exc:
                rate_limited = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
                if not rate_limited or attempt == 3:
                    raise
                time.sleep(10 * (attempt + 1))
        return ""


def get_llm_client() -> LLMClient:
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        return GeminiClient()
    if provider == "anthropic":
        return AnthropicClient()
    raise RuntimeError(f"unknown LLM_PROVIDER: {provider}")