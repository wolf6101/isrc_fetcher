"""AI client factory."""
from __future__ import annotations


def create_ai_client(api_key: str, log=None):
    from isrc_fetcher.ai_openai import OpenAIClient
    return OpenAIClient(api_key, log=log)
