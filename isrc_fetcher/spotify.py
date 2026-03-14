"""Spotify API client for ISRC lookups."""
from __future__ import annotations

import random
import time
import base64
import requests

from isrc_fetcher import cancel


class SpotifyClient:
    """Fetches ISRC codes from Spotify's catalog."""

    TOKEN_URL = "https://accounts.spotify.com/api/token"
    SEARCH_URL = "https://api.spotify.com/v1/search"

    def __init__(self, client_id: str, client_secret: str, log=None, label: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._token_expires = 0
        self._last_request_time = 0
        self._label = label
        _raw_log = log or (lambda msg: None)
        self._log = (lambda msg: _raw_log(f"[Spotify {label}] {msg}")) if label else _raw_log
        self._banned_until = 0  # timestamp when ban expires
        # Spotify: 1 req/s to stay safe within rolling 30s window
        self._min_interval = 1.0

    def _authenticate(self):
        """Get or refresh the access token using client credentials flow."""
        if self._token and time.time() < self._token_expires:
            return
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        last_err = None
        for attempt in range(3):
            try:
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
                return
            except (requests.RequestException, requests.Timeout) as e:
                last_err = e
                wait = 2 * (attempt + 1)
                self._log(
                    f"WARNING: Spotify auth failed: {e}. "
                    f"Retrying in {wait}s (attempt {attempt + 1}/3)"
                )
                cancel.sleep(wait)
        raise requests.RequestException(f"Spotify auth failed after 3 attempts: {last_err}")

    def _rate_limit(self):
        """Enforce minimum interval between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            cancel.sleep(self._min_interval - elapsed)

    def _search(self, query: str, limit: int = 10) -> dict:
        """Execute a Spotify search query with rate limiting and retry."""
        if self._banned_until > time.time():
            raise requests.RequestException("Spotify is paused (rate limit ban)")
        self._authenticate()
        for attempt in range(4):  # up to 3 retries
            self._rate_limit()
            resp = requests.get(
                self.SEARCH_URL,
                headers={"Authorization": f"Bearer {self._token}"},
                params={"q": query, "type": "track", "limit": limit},
                timeout=15,
            )
            self._last_request_time: float = time.time()
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5))
                # If Retry-After is absurdly long (>60s), Spotify has likely
                # banned this key — don't wait, fall back to MusicBrainz
                if retry_after > 60:
                    self._banned_until = time.time() + retry_after
                    self._log(
                        f"WARNING: Spotify rate limit hit (HTTP 429). "
                        f"Retry-After: {retry_after}s ({retry_after // 3600}h {retry_after % 3600 // 60}m) — "
                        f"Spotify paused until ban expires"
                    )
                    raise requests.RequestException(
                        f"Spotify rate limit: Retry-After {retry_after}s is too long"
                    )
                jitter = random.uniform(0.5, 2.0)
                wait = retry_after + jitter
                self._log(
                    f"WARNING: Spotify rate limit hit (HTTP 429). "
                    f"Retry-After: {retry_after}s + {jitter:.1f}s jitter. Attempt {attempt + 1}/4"
                )
                if attempt >= 3:
                    self._log("WARNING: Spotify rate limit — giving up after 4 attempts, skipping track")
                    raise requests.RequestException(
                        f"Spotify rate limit exceeded after {attempt + 1} attempts"
                    )
                cancel.sleep(wait)
                continue
            if resp.status_code != 200:
                self._log(f"WARNING: Spotify returned HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        return {"tracks": {"items": []}}

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

            track_artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
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
        if self._banned_until > time.time():
            return []

        queries = [
            f'track:"{title}" artist:"{artist}"',
            f'track:"{self._clean_title(title)}" artist:"{artist}"',
            f'{title} {artist}',
        ]

        for query in queries:
            try:
                data = self._search(query)
            except requests.RequestException as e:
                if self._banned_until > time.time():
                    return []  # banned — stop trying, no spam
                self._log(f"WARNING: Spotify search failed: {e}")
                continue
            results = self._extract_results(data, duration_seconds)
            if results:
                return results

        return []


class SpotifyPool:
    """Manages multiple Spotify accounts with automatic failover."""

    def __init__(self, accounts: list[dict], log=None):
        self._log = log or (lambda msg: None)
        self._clients: list[SpotifyClient] = []
        for i, acct in enumerate(accounts, 1):
            cid = acct.get("client_id", "")
            sec = acct.get("client_secret", "")
            if cid and sec:
                self._clients.append(SpotifyClient(cid, sec, log=log, label=f"#{i}"))
        self.last_account = ""
        if self._clients:
            self._log(f"Spotify: {len(self._clients)} account(s) configured")

    def search_isrc(
        self, title: str, artist: str, duration_seconds: int | None = None
    ) -> list[dict]:
        for client in self._clients:
            if client._banned_until > time.time():
                continue  # skip banned account
            results = client.search_isrc(title, artist, duration_seconds)
            if results:
                self.last_account = client._label
                return results
        return []
