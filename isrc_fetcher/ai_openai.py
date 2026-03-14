"""OpenAI provider for track operations.

Uses gpt-4o-mini — cheap, fast, and reliable.
"""
from __future__ import annotations

import json
import requests

from isrc_fetcher import cancel

from isrc_fetcher.ai_prompts import (
    build_clean_prompt, build_eval_prompt,
    parse_clean_response, parse_eval_response,
)


API_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"


PRICE_INPUT_PER_M  = 0.150  # USD per 1M input tokens (gpt-4o-mini)
PRICE_OUTPUT_PER_M = 0.600  # USD per 1M output tokens (gpt-4o-mini)


class OpenAIClient:
    """OpenAI client for batch track operations."""

    def __init__(self, api_key: str, log=None):
        self._api_key = api_key
        self._log = log or (lambda msg: None)
        self.tokens_in  = 0
        self.tokens_out = 0

    @property
    def cost_usd(self) -> float:
        return (self.tokens_in / 1_000_000) * PRICE_INPUT_PER_M + \
               (self.tokens_out / 1_000_000) * PRICE_OUTPUT_PER_M

    def _call(self, prompt: str) -> str:
        """Make an OpenAI API call and return the text response."""
        for attempt in range(3):
            try:
                resp = requests.post(
                    API_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": MODEL,
                        "temperature": 0.1,
                        "messages": [
                            {"role": "system", "content": "You are a music metadata expert. Respond only with valid JSON, no markdown, no explanation."},
                            {"role": "user", "content": prompt},
                        ],
                        "response_format": {"type": "json_object"},
                    },
                    timeout=300,
                )

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 10 * (attempt + 1)))
                    self._log(f"[OpenAI] Rate limited, waiting {retry_after}s...")
                    cancel.sleep(retry_after)
                    continue

                if resp.status_code != 200:
                    self._log(f"[OpenAI] HTTP {resp.status_code}: {resp.text[:200]}")
                    if attempt >= 2:
                        return ""
                    cancel.sleep(2)
                    continue

                data = resp.json()
                usage = data.get("usage", {})
                self.tokens_in  += usage.get("prompt_tokens", 0)
                self.tokens_out += usage.get("completion_tokens", 0)
                text = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                self._log(f"[AI:raw] [OpenAI] Response: {text[:300]}")
                return text

            except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
                self._log(f"[OpenAI] Error: {e}. Attempt {attempt + 1}/3")
                if attempt >= 2:
                    return ""
                cancel.sleep(2)

        return ""

    def clean_batch(self, batch: list[dict]) -> list[dict]:
        """Generate search queries and fix track metadata."""
        if not batch:
            return []
        text = self._call(build_clean_prompt(batch))
        if not text:
            return []
        result = parse_clean_response(text, batch)
        if not result:
            self._log("[OpenAI] Failed to parse clean response")
        return result

    def evaluate_batch(self, batch: list[dict]) -> list[dict]:
        """Pick best candidate for each track from search results."""
        if not batch:
            return []
        text = self._call(build_eval_prompt(batch))
        if not text:
            return []
        result = parse_eval_response(text, batch)
        if not result:
            self._log("[OpenAI] Failed to parse eval response")
        return result
