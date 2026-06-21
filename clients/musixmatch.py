"""Musixmatch client (Pro plan).

Resolve a track by ISRC (preferred) or title+artist, then pull full lyrics.
Returns the ISRC, which is the join key into Songstats.
Docs: https://developer.musixmatch.com/documentation
"""
import httpx
from config import MUSIXMATCH_API_KEY

BASE = "https://api.musixmatch.com/ws/1.1"


class MusixmatchError(Exception):
    def __init__(self, code, path):
        super().__init__(f"Musixmatch {path} -> status {code}")
        self.code = code


def _get(path, **params):
    params["apikey"] = MUSIXMATCH_API_KEY
    params.setdefault("format", "json")
    r = httpx.get(f"{BASE}/{path}", params=params, timeout=30)
    r.raise_for_status()
    msg = r.json()["message"]
    code = msg["header"]["status_code"]
    # 401 bad key, 402 quota / licensed-feature not in plan, 404 not found
    if code != 200:
        raise MusixmatchError(code, path)
    return msg["body"]


def _fields(t):
    genres = [g["music_genre"]["music_genre_name"]
              for g in (t.get("primary_genres", {}).get("music_genre_list") or [])]
    return {
        "commontrack_id": t.get("commontrack_id"),
        "title":  t.get("track_name", ""),
        "artist": t.get("artist_name", ""),
        "album":  t.get("album_name", ""),
        "isrc":   t.get("track_isrc", ""),
        "explicit":     bool(t.get("explicit", 0)),
        "has_lyrics":   bool(t.get("has_lyrics", 0)),
        "instrumental": bool(t.get("instrumental", 0)),
        "genre":  genres[0] if genres else "",
        "year":   (t.get("first_release_date", "") or "")[:4],
    }


def match_by_isrc(isrc):
    """track.get accepts track_isrc on commercial/Pro plans."""
    body = _get("track.get", track_isrc=isrc)
    t = body.get("track")
    return _fields(t) if t else None


def match_by_name(title, artist):
    """matcher.track.get does the fuzzy resolution for you."""
    body = _get("matcher.track.get", q_track=title, q_artist=artist)
    t = body.get("track")
    return _fields(t) if t else None


def get_lyrics(commontrack_id):
    body = _get("track.lyrics.get", commontrack_id=commontrack_id)
    ly = body.get("lyrics") or {}
    return {
        "body":     ly.get("lyrics_body", ""),
        "language": ly.get("lyrics_language", ""),
        "explicit": bool(ly.get("explicit", 0)),
    }


def get_translation(commontrack_id, selected_language="en"):
    """Translated lyrics in `selected_language` (ISO code) via track.lyrics.translation.get.
    Requires the translation entitlement on the plan (402 if not included). Response shape
    varies, so we dig defensively. Returns "" when no translation is available."""
    try:
        body = _get("track.lyrics.translation.get",
                    commontrack_id=commontrack_id, selected_language=selected_language)
    except Exception:
        return ""  # 402 = not in plan, 404 = no translation, etc. — just skip translating

    # Form 1: a translated lyrics object (most common)
    ly = body.get("lyrics") or {}
    if ly.get("lyrics_body"):
        return ly["lyrics_body"]

    # Form 2: a line-by-line translation_list
    lines = []
    for item in (body.get("translation_list") or []):
        tr = (item or {}).get("translation") or {}
        line = tr.get("snippet_translated") or tr.get("description_translated") or ""
        if line:
            lines.append(line)
    if lines:
        return "\n".join(lines)

    # Form 3: last resort — walk for any translated body
    found = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("lyrics_body", "snippet_translated", "description_translated") \
                        and isinstance(v, str) and v.strip():
                    found.append(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(body)
    return found[0] if found else ""
