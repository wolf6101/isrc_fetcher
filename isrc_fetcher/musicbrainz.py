"""MusicBrainz API client for ISRC lookups."""
from __future__ import annotations

import time
import requests


class MusicBrainzClient:
    """Fetches ISRC codes from MusicBrainz as a fallback source."""

    BASE_URL = "https://musicbrainz.org/ws/2"
    USER_AGENT = "ISRCFetcher/1.0 (Excel Add-in)"

    def __init__(self):
        self._last_request_time = 0
        # MusicBrainz: max 1 request per second
        self._min_interval = 1.1

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _get(self, endpoint: str, params: dict) -> dict:
        self._rate_limit()
        params["fmt"] = "json"
        resp = requests.get(
            f"{self.BASE_URL}/{endpoint}",
            params=params,
            headers={"User-Agent": self.USER_AGENT},
            timeout=15,
        )
        self._last_request_time = time.time()
        if resp.status_code == 503:
            time.sleep(2)
            return self._get(endpoint, params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _clean_title(title: str) -> str:
        import re
        cleaned = re.sub(r'\s*[\(\[].*?[\)\]]', '', title)
        cleaned = re.sub(r'\s*(feat\.?|ft\.?|featuring)\s+.*', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip() or title

    def _extract_results(self, data: dict, duration_seconds: int | None) -> list[dict]:
        recordings = data.get("recordings", [])
        results = []
        seen_isrcs = set()

        for rec in recordings:
            isrcs = rec.get("isrcs", [])
            if not isrcs:
                continue

            rec_artists = ", ".join(
                credit.get("name", "")
                for credit in rec.get("artist-credit", [])
                if isinstance(credit, dict) and "name" in credit
            )
            length_ms = rec.get("length") or 0

            for isrc in isrcs:
                if isrc in seen_isrcs:
                    continue
                seen_isrcs.add(isrc)

                duration_match = None
                if duration_seconds is not None and length_ms:
                    track_secs = length_ms / 1000
                    duration_match = abs(track_secs - duration_seconds) <= 5

                results.append({
                    "isrc": isrc,
                    "name": rec.get("title", ""),
                    "artist": rec_artists,
                    "duration_ms": length_ms,
                    "duration_match": duration_match,
                })

        return results

    def search_isrc(
        self, title: str, artist: str, duration_seconds: int | None = None
    ) -> list[dict]:
        """Search MusicBrainz for ISRC codes matching a song.

        Tries exact query first, then broader queries if nothing found.
        Returns same format as SpotifyClient.search_isrc.
        """
        queries = [
            f'recording:"{title}" AND artist:"{artist}"',
            f'recording:"{self._clean_title(title)}" AND artist:"{artist}"',
            f'recording:({title}) AND artist:({artist})',
        ]

        for query in queries:
            try:
                data = self._get("recording", {"query": query, "limit": 10})
            except requests.RequestException:
                continue
            results = self._extract_results(data, duration_seconds)
            if results:
                return results

        return []
