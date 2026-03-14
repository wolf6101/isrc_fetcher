"""AI-powered resolver for failed/mismatched tracks.

Second pass: relaxed search across all sources, then AI picks the best match.
Batches tracks for efficient LLM usage.
"""
from __future__ import annotations

import re

from isrc_fetcher.ai_client import create_ai_client
from isrc_fetcher.deezer import DeezerClient
from isrc_fetcher.musicbrainz import MusicBrainzClient
from isrc_fetcher.spotify import SpotifyPool


BATCH_SIZE = 15  # tracks per AI call


class TrackResolver:
    """Resolves failed tracks using relaxed search + AI evaluation."""

    def __init__(
        self,
        ai_api_key: str,
        spotify_accounts: list[dict] | None = None,
        log=None,
    ):
        self._log = log or (lambda msg: None)
        self.ai = create_ai_client(ai_api_key, log=log)
        self.deezer = DeezerClient(log=log)
        self.musicbrainz = MusicBrainzClient(log=log)
        self.spotify = SpotifyPool(spotify_accounts or [], log=log) if spotify_accounts else None

    @staticmethod
    def _strip_title(title: str) -> str:
        """Aggressively strip title for broad search."""
        # Remove anything in parens/brackets
        cleaned = re.sub(r'\s*[\(\[].*?[\)\]]', '', title)
        # Remove feat/ft
        cleaned = re.sub(r'\s*(feat\.?|ft\.?|featuring)\s+.*', '', cleaned, flags=re.IGNORECASE)
        # Remove " - " suffix (e.g. "Song - Radio Edit")
        cleaned = re.sub(r'\s*-\s+.*$', '', cleaned)
        return cleaned.strip() or title

    @staticmethod
    def _title_keywords(title: str) -> str:
        """Extract just the main keywords from a title."""
        cleaned = TrackResolver._strip_title(title)
        # Remove common filler words
        words = cleaned.split()
        return " ".join(w for w in words if len(w) > 1)

    @staticmethod
    def _first_artist(artist: str) -> str:
        """Extract the first/primary artist name."""
        for sep in [',', '&', ' feat', ' ft', ' x ', ' X ', ' vs']:
            if sep.lower() in artist.lower():
                idx = artist.lower().index(sep.lower())
                part = artist[:idx].strip()
                if part:
                    return part
        return artist.strip()

    def _search_with_queries(self, queries: list[str]) -> list[dict]:
        """Search using AI-generated queries across Deezer and Spotify."""
        all_candidates = []
        seen_isrcs = set()

        def _add(results: list[dict]):
            for r in results:
                if r["isrc"] not in seen_isrcs:
                    seen_isrcs.add(r["isrc"])
                    all_candidates.append(r)

        for query in queries:
            if len(all_candidates) >= 20:
                break

            # Try on Deezer (fast, no auth needed)
            try:
                data = self.deezer._search(query, limit=10)
                _add(self.deezer._extract_results(data, None))
            except Exception:
                pass

            if len(all_candidates) >= 20:
                break

            # Try on Spotify if it looks like a Spotify-formatted query
            if self.spotify and 'track:' in query:
                try:
                    for client in self.spotify._clients:
                        if client._banned_until > __import__('time').time():
                            continue
                        data = client._search(query, limit=10)
                        _add(client._extract_results(data, None))
                        break
                except Exception:
                    pass

        return all_candidates[:20]

    def _fallback_search(self, title: str, artist: str) -> list[dict]:
        """Fallback heuristic search if AI didn't provide queries."""
        queries = [
            f'{self._strip_title(title)} {self._first_artist(artist)}',
            f'{self._title_keywords(title)} {self._first_artist(artist)}',
            self._title_keywords(title),
        ]
        return self._search_with_queries(queries)

    def resolve(
        self,
        tracks: list[dict],
        on_progress=None,
        is_cancelled=None,
    ) -> list[dict]:
        """Resolve a list of failed/mismatched tracks.

        Each track:
            {"row": int, "title": str, "artist": str, "duration": str|None,
             "status": "Not found"|"Duration mismatch"}

        Args:
            is_cancelled: optional callable returning True if user hit Stop.

        Returns list of resolved tracks:
            [{"row": int, "isrc": str, "name": str, "artist": str,
              "duration_ms": int, "confidence": str, "reason": str}, ...]
        """
        if not tracks:
            return []
        _cancelled = is_cancelled or (lambda: False)

        self._log(f"[AI Resolve] Starting resolution of {len(tracks)} tracks")
        self._log(f"[AI Resolve] Batch size: {BATCH_SIZE} tracks per AI call")

        # Phase 1: Search for candidates using AI-generated queries
        self._log("[AI Resolve] Phase 1: Searching with AI-generated queries...")
        track_candidates = []
        for i, track in enumerate(tracks):
            if _cancelled():
                self._log("[AI Resolve] Cancelled by user.")
                break

            if on_progress:
                on_progress("search", i + 1, len(tracks))

            # Use AI-generated queries if available, otherwise fallback
            ai_queries = track.get("queries", [])
            if ai_queries:
                candidates = self._search_with_queries(ai_queries)
            else:
                candidates = self._fallback_search(track["title"], track["artist"])

            if candidates:
                track_candidates.append({
                    "track": track,
                    "candidates": candidates,
                })
                self._log(
                    f"[AI Resolve] [{i+1}/{len(tracks)}] "
                    f"{track['artist']} - {track['title']} → {len(candidates)} candidates"
                )
            else:
                self._log(
                    f"[AI Resolve] [{i+1}/{len(tracks)}] "
                    f"{track['artist']} - {track['title']} → no candidates found"
                )

        if not track_candidates:
            self._log("[AI Resolve] No candidates found for any track")
            return []

        # Phase 2: Batch evaluate with AI
        self._log(
            f"[AI Resolve] Phase 2: AI evaluation — "
            f"{len(track_candidates)} tracks with candidates, "
            f"{(len(track_candidates) + BATCH_SIZE - 1) // BATCH_SIZE} AI calls needed"
        )

        resolved = []
        batch_num = 0

        for start in range(0, len(track_candidates), BATCH_SIZE):
            if _cancelled():
                self._log("[AI Resolve] Cancelled by user.")
                break

            batch_num += 1
            chunk = track_candidates[start:start + BATCH_SIZE]

            batch_input = []
            for item in chunk:
                t = item["track"]
                batch_input.append({
                    "index": t["row"],
                    "title": t["title"],
                    "artist": t["artist"],
                    "duration": t.get("duration"),
                    "candidates": item["candidates"],
                })

            total_batches = (len(track_candidates) + BATCH_SIZE - 1) // BATCH_SIZE
            self._log(f"[AI Resolve] Sending batch {batch_num}/{total_batches} to AI...")

            if on_progress:
                on_progress("ai", start + len(chunk), len(track_candidates))

            decisions = self.ai.evaluate_batch(batch_input)

            for decision in decisions:
                if decision["pick"] is None:
                    continue

                # Find the matching track and candidate
                item = next(
                    (c for c in chunk if c["track"]["row"] == decision["index"]),
                    None,
                )
                if not item:
                    continue

                pick_idx = decision["pick"]
                if pick_idx >= len(item["candidates"]):
                    continue

                candidate = item["candidates"][pick_idx]
                resolved.append({
                    "row": decision["index"],
                    "isrc": candidate["isrc"],
                    "name": candidate["name"],
                    "artist": candidate["artist"],
                    "duration_ms": candidate.get("duration_ms", 0),
                    "confidence": decision["confidence"],
                    "reason": decision["reason"],
                })

                self._log(
                    f"[AI Resolve] R{decision['index']}: "
                    f"→ {candidate['isrc']} ({decision['confidence']}) "
                    f"— {decision['reason']}"
                )

        not_resolved = len(tracks) - len(resolved)
        self._log(
            f"[AI Resolve] Done! Resolved: {len(resolved)} | "
            f"Still unresolved: {not_resolved}"
        )

        return resolved
