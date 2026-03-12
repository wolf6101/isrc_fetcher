"""Core ISRC fetching logic — combines Spotify + MusicBrainz results."""
from __future__ import annotations

import re

from isrc_fetcher.spotify import SpotifyClient
from isrc_fetcher.musicbrainz import MusicBrainzClient


class ISRCFetcher:
    """Orchestrates ISRC lookups across multiple sources."""

    def __init__(
        self,
        spotify_client_id: str | None = None,
        spotify_client_secret: str | None = None,
    ):
        self.spotify = None
        self.musicbrainz = MusicBrainzClient()

        if spotify_client_id and spotify_client_secret:
            self.spotify = SpotifyClient(spotify_client_id, spotify_client_secret)

    @staticmethod
    def _artist_variants(artist: str) -> list[str]:
        """Generate artist name variants for broader matching.

        Handles comma-separated artists, leading special chars, etc.
        E.g. '¡¡O,AMANDA WILSON,FREEMASONS' -> ['¡¡O,AMANDA WILSON,FREEMASONS',
             'AMANDA WILSON', 'FREEMASONS', '¡¡O']
        """
        variants = [artist]
        # Strip leading/trailing non-alphanumeric chars
        stripped = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', artist)
        if stripped and stripped != artist:
            variants.append(stripped)
        # Split comma-separated artists and try each
        if ',' in artist:
            parts = [p.strip() for p in artist.split(',') if p.strip()]
            for part in parts:
                cleaned = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', part)
                if cleaned and cleaned not in variants:
                    variants.append(cleaned)
        return variants

    def _search_all_sources(
        self, title: str, artist: str, duration_seconds: int | None
    ) -> list[dict]:
        """Try Spotify first, fall back to MusicBrainz."""
        results = []
        if self.spotify:
            results = self.spotify.search_isrc(title, artist, duration_seconds)
        if not results:
            results = self.musicbrainz.search_isrc(title, artist, duration_seconds)
        return results

    def fetch(
        self,
        title: str,
        artist: str,
        duration_seconds: int | None = None,
    ) -> dict:
        """Fetch ISRC for a song. Tries multiple artist variants.

        Returns:
            {
                "isrc": str or None,
                "exact_match": bool,
                "warning": str or None,
                "all_results": list[dict],
            }
        """
        all_results = []

        # Try each artist variant until we find results
        for artist_variant in self._artist_variants(artist):
            all_results = self._search_all_sources(
                title, artist_variant, duration_seconds
            )
            if all_results:
                break

        if not all_results:
            return {
                "isrc": None,
                "exact_match": False,
                "warning": "No results found",
                "all_results": [],
                "matched": None,
            }

        def _pack(r, exact_match, warning):
            return {
                "isrc": r["isrc"],
                "exact_match": exact_match,
                "warning": warning,
                "all_results": all_results,
                "matched": r,
            }

        # If we have duration, prefer exact duration matches
        if duration_seconds is not None:
            exact = [r for r in all_results if r.get("duration_match") is True]
            if exact:
                return _pack(exact[0], True, None)
            return _pack(all_results[0], False, "Duration mismatch (>5s difference)")

        # No duration to compare — return first result
        return _pack(all_results[0], True, None)
