"""Spotify API client for ISRC lookups."""
from __future__ import annotations

import time
import base64
import requests


class SpotifyClient:
    """Fetches ISRC codes from Spotify's catalog."""

    TOKEN_URL = "https://accounts.spotify.com/api/token"
    SEARCH_URL = "https://api.spotify.com/v1/search"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._token_expires = 0
        self._last_request_time = 0
        # Spotify rate limit: be gentle, ~10 req/s
        self._min_interval = 0.15

    def _authenticate(self):
        """Get or refresh the access token using client credentials flow."""
        if self._token and time.time() < self._token_expires:
            return
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        resp = requests.post(
            self.TOKEN_URL,
            headers={"Authorization": f"Basic {credentials}"},
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Refresh 60s before actual expiry
        self._token_expires = time.time() + data["expires_in"] - 60

    def _rate_limit(self):
        """Enforce minimum interval between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _search(self, query: str, limit: int = 10) -> dict:
        """Execute a Spotify search query with rate limiting and retry."""
        self._authenticate()
        self._rate_limit()
        resp = requests.get(
            self.SEARCH_URL,
            headers={"Authorization": f"Bearer {self._token}"},
            params={"q": query, "type": "track", "limit": limit},
            timeout=15,
        )
        self._last_request_time = time.time()
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            time.sleep(retry_after)
            return self._search(query, limit)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _clean_title(title: str) -> str:
        """Strip feat/remix/bracket annotations for broader matching."""
        import re
        cleaned = re.sub(r'\s*[\(\[].*?[\)\]]', '', title)
        cleaned = re.sub(r'\s*(feat\.?|ft\.?|featuring)\s+.*', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip() or title

    def _extract_results(self, data: dict, duration_seconds: int | None) -> list[dict]:
        tracks = data.get("tracks", {}).get("items", [])
        results = []
        seen_isrcs = set()

        for track in tracks:
            isrc = track.get("external_ids", {}).get("isrc")
            if not isrc or isrc in seen_isrcs:
                continue
            seen_isrcs.add(isrc)

            track_artists = ", ".join(a["name"] for a in track.get("artists", []))
            duration_ms = track.get("duration_ms", 0)

            duration_match = None
            if duration_seconds is not None and duration_ms:
                track_secs = duration_ms / 1000
                duration_match = abs(track_secs - duration_seconds) <= 5

            results.append({
                "isrc": isrc,
                "name": track.get("name", ""),
                "artist": track_artists,
                "duration_ms": duration_ms,
                "duration_match": duration_match,
            })

        return results

    def search_isrc(
        self, title: str, artist: str, duration_seconds: int | None = None
    ) -> list[dict]:
        """Search for ISRC codes matching a song.

        Tries exact query first, then broader queries if nothing found.
        Returns a list of dicts: [{"isrc": str, "name": str, "artist": str,
        "duration_ms": int, "duration_match": bool | None}]
        """
        queries = [
            f'track:"{title}" artist:"{artist}"',
            f'track:"{self._clean_title(title)}" artist:"{artist}"',
            f'{title} {artist}',
        ]

        for query in queries:
            try:
                data = self._search(query)
            except requests.RequestException:
                continue
            results = self._extract_results(data, duration_seconds)
            if results:
                return results

        return []
