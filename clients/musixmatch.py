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
