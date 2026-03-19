"""ISRC Validator — looks up existing ISRC codes and compares stored metadata."""
from __future__ import annotations

import difflib
import re
import time

import requests

from isrc_fetcher import cancel


def _normalize(s: str) -> str:
    """Lowercase, strip punctuation and extra spaces for comparison."""
    s = s.lower().strip()
    s = re.sub(r'[^\w\s]', '', s)
    s = re.sub(r'\s+', ' ', s)
    return s


def _similarity(a: str, b: str) -> float:
    """String similarity ratio 0.0–1.0."""
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


class ISRCValidator:
    """Validates existing ISRC codes by looking them up and comparing metadata."""

    def __init__(self, spotify_accounts=None, log=None):
        self._log = log or (lambda msg: None)
        self._last_deezer_time: float = 0.0
        from isrc_fetcher.musicbrainz import MusicBrainzClient
        self._mb = MusicBrainzClient(log=log)
        self._spotify = None
        if spotify_accounts:
            from isrc_fetcher.spotify import SpotifyPool
            self._spotify = SpotifyPool(spotify_accounts, log=log)

    # ── Deezer direct ISRC lookup ─────────────────────────────────────────

    def _deezer_lookup(self, isrc: str) -> dict | None:
        """GET https://api.deezer.com/track/isrc:{isrc} — returns track dict or None."""
        elapsed = time.time() - self._last_deezer_time
        if elapsed < 0.25:
            cancel.sleep(0.25 - elapsed)

        url = f"https://api.deezer.com/track/isrc:{isrc}"
        for attempt in range(4):
            try:
                resp = requests.get(url, timeout=15)
            except (requests.ConnectionError, requests.Timeout) as e:
                self._log(f"WARNING: Deezer connection error: {e}. Attempt {attempt + 1}/4")
                if attempt >= 3:
                    raise
                cancel.sleep(2 * (attempt + 1))
                continue

            self._last_deezer_time = time.time()
            data = resp.json()

            if "error" in data:
                code = data["error"].get("code", 0)
                if code == 4:  # quota exceeded
                    wait = 5 * (attempt + 1)
                    self._log(f"WARNING: Deezer quota exceeded. Waiting {wait}s.")
                    if attempt >= 3:
                        return None
                    cancel.sleep(wait)
                    continue
                return None  # ISRC not found in Deezer

            if data.get("id"):
                dur_s = data.get("duration", 0)
                return {
                    "name": data.get("title", ""),
                    "artist": data.get("artist", {}).get("name", ""),
                    "duration_ms": dur_s * 1000,
                }
            return None

        return None

    # ── MusicBrainz direct ISRC lookup ───────────────────────────────────

    def _musicbrainz_lookup(self, isrc: str) -> dict | None:
        """GET /ws/2/isrc/{code}?inc=recordings — returns first recording or None."""
        try:
            data = self._mb._get(f"isrc/{isrc}", {"inc": "recordings artist-credits"})
        except Exception as e:
            self._log(f"WARNING: MusicBrainz ISRC lookup failed: {e}")
            return None

        recordings = data.get("recordings", [])
        if not recordings:
            return None

        rec = recordings[0]
        artists = ", ".join(
            credit.get("name", "")
            for credit in rec.get("artist-credit", [])
            if isinstance(credit, dict) and "name" in credit
        )
        return {
            "name": rec.get("title", ""),
            "artist": artists,
            "duration_ms": rec.get("length") or 0,
        }

    # ── Spotify ISRC lookup ───────────────────────────────────────────────

    def _spotify_lookup(self, isrc: str) -> dict | None:
        """Search Spotify with isrc:{code} query."""
        if not self._spotify or not self._spotify._clients:
            return None
        for client in self._spotify._clients:
            if client._banned_until > time.time():
                continue
            try:
                data = client._search(f"isrc:{isrc}", limit=1)
                items = data.get("tracks", {}).get("items", [])
                if items:
                    t = items[0]
                    artists = ", ".join(a.get("name", "") for a in t.get("artists", []))
                    return {
                        "name": t.get("name", ""),
                        "artist": artists,
                        "duration_ms": t.get("duration_ms", 0),
                    }
            except Exception as e:
                self._log(f"WARNING: Spotify ISRC lookup failed: {e}")
                continue
        return None

    # ── Main validate method ──────────────────────────────────────────────

    def validate(
        self,
        isrc: str,
        title: str,
        artist: str,
        duration_seconds: int | None,
    ) -> dict:
        """Look up an ISRC and compare with the expected metadata.

        Returns:
            {
                "status": str,          # "Valid" | issue description(s)
                "found_title": str,
                "found_artist": str,
                "found_duration": str,  # "M:SS" or ""
            }
        """
        # 1. Deezer — direct ISRC endpoint, no auth
        found = self._deezer_lookup(isrc)
        source = "Deezer"

        # 2. MusicBrainz — direct ISRC endpoint, no auth
        if not found:
            found = self._musicbrainz_lookup(isrc)
            source = "MusicBrainz"

        # 3. Spotify — ISRC filter query, needs credentials
        if not found:
            found = self._spotify_lookup(isrc)
            source = "Spotify"

        if not found:
            return {
                "status": "ISRC not found",
                "found_title": "",
                "found_artist": "",
                "found_duration": "",
            }

        # 3. Compare metadata
        issues = []

        title_sim = _similarity(title, found["name"])
        if title_sim < 0.6:
            issues.append("Title mismatch")

        artist_sim = _similarity(artist, found["artist"])
        if artist_sim < 0.5:
            issues.append("Artist mismatch")

        dur_ms = found.get("duration_ms", 0)
        dur_str = ""
        if dur_ms:
            s = int(dur_ms // 1000)
            dur_str = f"{s // 60}:{s % 60:02d}"
            if duration_seconds and abs(s - duration_seconds) > 5:
                issues.append("Duration mismatch")

        status = " · ".join(issues) if issues else "Valid"

        return {
            "status": status,
            "found_title": found["name"],
            "found_artist": found["artist"],
            "found_duration": dur_str,
            "source": source,
        }
