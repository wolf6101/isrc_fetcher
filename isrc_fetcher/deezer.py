"""Deezer API client for ISRC lookups.

No authentication required. Rate limit: 50 requests per 5 seconds.
"""
from __future__ import annotations

import re
import time
import requests

from isrc_fetcher import cancel


class DeezerClient:
    """Fetches ISRC codes from Deezer's catalog."""

    SEARCH_URL = "https://api.deezer.com/search/track"

    def __init__(self, log=None):
        self._last_request_time = 0
        self._log = log or (lambda msg: None)
        # Deezer: 50 req/5s = 1 req per 0.1s, use 0.2 for safe bulk processing
        self._min_interval = 0.2

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            cancel.sleep(self._min_interval - elapsed)

    def _search(self, query: str, limit: int = 10) -> dict:
        """Execute a Deezer search query with rate limiting and retry."""
        for attempt in range(4):
            self._rate_limit()
            try:
                resp = requests.get(
                    self.SEARCH_URL,
                    params={"q": query, "limit": limit},
                    timeout=15,
                )
            except (requests.ConnectionError, requests.Timeout) as e:
                self._log(f"WARNING: Deezer connection error: {e}. Attempt {attempt + 1}/4")
                if attempt >= 3:
                    raise
                cancel.sleep(2 * (attempt + 1))
                continue
            self._last_request_time = time.time()

            data = resp.json()

            # Deezer returns errors as JSON with an "error" key
            if "error" in data:
                error_code = data["error"].get("code", 0)
                error_msg = data["error"].get("message", "Unknown error")
                if error_code == 4:  # Quota exceeded
                    wait = 5 * (attempt + 1)
                    self._log(
                        f"WARNING: Deezer quota exceeded. "
                        f"Waiting {wait}s. Attempt {attempt + 1}/4"
                    )
                    if attempt >= 3:
                        self._log("WARNING: Deezer quota — giving up after 4 attempts")
                        raise requests.RequestException(f"Deezer quota exceeded: {error_msg}")
                    cancel.sleep(wait)
                    continue
                self._log(f"WARNING: Deezer API error: {error_msg} (code {error_code})")
                raise requests.RequestException(f"Deezer error: {error_msg}")

            return data

        return {"data": []}

    @staticmethod
    def _clean_title(title: str) -> str:
        """Strip feat/remix/bracket annotations for broader matching."""
        cleaned = re.sub(r'\s*[\(\[].*?[\)\]]', '', title)
        cleaned = re.sub(r'\s*(feat\.?|ft\.?|featuring)\s+.*', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip() or title

    def _extract_results(self, data: dict, duration_seconds: int | None) -> list[dict]:
        tracks = data.get("data", [])
        results = []
        seen_isrcs = set()

        for track in tracks:
            isrc = track.get("isrc")
            if not isrc or isrc in seen_isrcs:
                continue
            seen_isrcs.add(isrc)

            artist_name = track.get("artist", {}).get("name", "")
            duration_s = track.get("duration", 0)
            duration_ms = duration_s * 1000

            duration_match = None
            if duration_seconds is not None and duration_s:
                duration_match = abs(duration_s - duration_seconds) <= 5

            results.append({
                "isrc": isrc,
                "name": track.get("title", ""),
                "artist": artist_name,
                "duration_ms": duration_ms,
                "duration_match": duration_match,
            })

        return results

    def search_isrc(
        self, title: str, artist: str, duration_seconds: int | None = None
    ) -> list[dict]:
        """Search Deezer for ISRC codes matching a song.

        Tries exact query first, then broader queries if nothing found.
        Returns same format as SpotifyClient.search_isrc.
        """
        queries = [
            f'track:"{title}" artist:"{artist}"',
            f'track:"{self._clean_title(title)}" artist:"{artist}"',
            f'{title} {artist}',
        ]

        for query in queries:
            try:
                data = self._search(query)
            except requests.RequestException as e:
                self._log(f"WARNING: Deezer search failed: {e}")
                continue
            results = self._extract_results(data, duration_seconds)
            if results:
                return results

        return []
