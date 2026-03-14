"""Shared AI prompts and response parsing for track operations."""
from __future__ import annotations

import json


def build_clean_prompt(batch: list[dict]) -> str:
    """Build prompt for generating search queries from track metadata."""
    tracks_text = []
    for item in batch:
        tracks_text.append(
            f'{{"index": {item["index"]}, '
            f'"title": {json.dumps(item["title"])}, '
            f'"artist": {json.dumps(item["artist"])}}}'
        )

    return (
        "You are a music metadata expert. These tracks were NOT found in music "
        "databases (Deezer, Spotify). Generate search queries to find them.\n\n"
        "For EACH track, produce:\n"
        "1. corrected_title — fix any typos, standardize accents (Beyonce → Beyoncé)\n"
        "2. corrected_artist — fix typos, standardize names\n"
        "3. queries — a list of 3-5 search query strings to try on Deezer/Spotify, "
        "ordered from most specific to most broad. These should be creative:\n"
        "   - Try the corrected exact title + artist\n"
        "   - Try alternative/common title spellings or translations people might use\n"
        "   - Try just the main keywords without remix/feat/version tags\n"
        "   - Try the primary artist only (if multiple artists listed)\n"
        "   - Try known aliases or stage name variations of the artist\n"
        "   - If the title might be known by a different name, include that\n\n"
        "Rules:\n"
        "- Keep original language — do NOT translate unless the song is commonly "
        "known in another language in music databases\n"
        "- For Deezer queries use format: artist name song title (plain text)\n"
        "- For Spotify queries use format: track:\"title\" artist:\"artist\"\n"
        "- Mix both formats in the queries list\n"
        "- Be creative — think about how this song might be catalogued differently\n"
        "- If an artist has a well-known alias, include queries with both names\n\n"
        "Tracks:\n" + "\n".join(tracks_text) + "\n\n"
        "Respond with a JSON array. One object per track:\n"
        '{"index": <index>, "corrected_title": "...", "corrected_artist": "...", '
        '"queries": ["query1", "query2", ...]}\n\n'
        "Return ONLY the JSON array."
    )


def build_eval_prompt(batch: list[dict]) -> str:
    """Build prompt for evaluating track candidates."""
    tracks_text = []
    for item in batch:
        dur = item.get("duration") or "unknown"
        candidates_text = []
        for j, c in enumerate(item["candidates"]):
            c_dur = c.get("duration_ms", 0)
            c_dur_str = f"{c_dur // 1000 // 60}:{c_dur // 1000 % 60:02d}" if c_dur else "?"
            candidates_text.append(
                f"    [{j}] \"{c['name']}\" by {c['artist']} "
                f"(duration: {c_dur_str}, ISRC: {c['isrc']})"
            )

        tracks_text.append(
            f"TRACK {item['index']}:\n"
            f"  Looking for: \"{item['title']}\" by {item['artist']} "
            f"(duration: {dur})\n"
            f"  Candidates:\n" + "\n".join(candidates_text)
        )

    return (
        "You are a music metadata expert. For each track below, pick the best "
        "matching candidate or reject all if none match.\n\n"
        "Rules:\n"
        "- Match by title similarity, artist match, and duration closeness\n"
        "- Title variations are OK: remix tags, feat. credits, punctuation differences\n"
        "- Artist order or slight name differences are OK (e.g. 'The Beatles' vs 'Beatles')\n"
        "- Duration within 10 seconds is acceptable (radio edits, fades)\n"
        "- Duration within 30 seconds is acceptable IF title and artist match well\n"
        "- Reject if title is clearly a different song or artist is completely wrong\n"
        "- For live/acoustic/remix versions: only accept if the original also seems "
        "to be that version\n\n"
        + "\n\n".join(tracks_text) + "\n\n"
        "Respond with a JSON array. One object per track:\n"
        '{"index": <track index>, "pick": <candidate index or null>, '
        '"confidence": "high"|"medium"|"low", "reason": "<brief explanation>"}\n\n'
        "Return ONLY the JSON array, no other text."
    )


def parse_json_array(text: str) -> list | None:
    """Parse JSON array from LLM response, stripping markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        result = json.loads(text)
        # Some providers wrap array in an object — extract it
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return v
            return None
        return result if isinstance(result, list) else None
    except json.JSONDecodeError:
        return None


def parse_clean_response(text: str, batch: list[dict]) -> list[dict]:
    """Parse clean/query-generation response.

    Returns list of:
        {"index": int, "title": str, "artist": str, "changed": bool,
         "queries": list[str]}
    """
    parsed = parse_json_array(text)
    if not parsed:
        return []

    originals = {item["index"]: item for item in batch}
    results = []
    for d in parsed:
        if not isinstance(d, dict) or "index" not in d:
            continue
        idx = d["index"]
        orig = originals.get(idx)
        if not orig:
            continue
        new_title = d.get("corrected_title", d.get("title", orig["title"]))
        new_artist = d.get("corrected_artist", d.get("artist", orig["artist"]))
        queries = d.get("queries", [])
        if not isinstance(queries, list):
            queries = []
        changed = (new_title != orig["title"]) or (new_artist != orig["artist"])
        results.append({
            "index": idx,
            "title": new_title,
            "artist": new_artist,
            "changed": changed,
            "queries": queries,
        })
    return results


def parse_eval_response(text: str, batch: list[dict]) -> list[dict]:
    """Parse eval response into decision list."""
    parsed = parse_json_array(text)
    if not parsed:
        return []

    valid = []
    for d in parsed:
        if not isinstance(d, dict) or "index" not in d:
            continue
        pick = d.get("pick")
        item = next((b for b in batch if b["index"] == d["index"]), None)
        if item and pick is not None:
            if not isinstance(pick, int) or pick < 0 or pick >= len(item["candidates"]):
                pick = None
        valid.append({
            "index": d["index"],
            "pick": pick,
            "confidence": d.get("confidence", "low"),
            "reason": d.get("reason", ""),
        })
    return valid
