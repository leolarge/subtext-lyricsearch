"""Songstats client — market data + the Spotify link for a track, keyed by ISRC.

NOTE: the first request for a brand-new ISRC triggers background aggregation and
returns little; data fills in on subsequent calls. Pre-warm your catalog before a demo.
Docs: https://docs.songstats.com
"""
import re
import httpx
from config import SONGSTATS_API_KEY

BASE = "https://api.songstats.com/enterprise/v1"
HEAD = {"apikey": SONGSTATS_API_KEY, "Accept": "application/json"}


def _get(path, **params):
    try:
        r = httpx.get(f"{BASE}/{path}", headers=HEAD, params=params, timeout=30)
    except Exception:
        return {}
    if r.status_code != 200:
        return {}
    try:
        return r.json()
    except Exception:
        return {}


def track_stats(isrc):
    return _get("tracks/stats", isrc=isrc, source="spotify")


def track_info(isrc):
    """Cross-platform metadata incl. the aggregated track links (Spotify, Apple, ...)."""
    return _get("tracks/info", isrc=isrc)


def _dig(obj, *keys):
    """Return the first numeric value found anywhere for each of `keys`."""
    found = {}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys and isinstance(v, (int, float)) and k not in found:
                    found[k] = v
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return found


def parse_market(raw):
    """Map Songstats' response to the fields we use. Field names vary by plan,
    so we search defensively. Confirm/adjust keys against the live docs."""
    f = _dig(raw,
             "streams_total", "spotify_streams_total",
             "popularity_current", "spotify_popularity_current",
             "playlists_total", "playlists_current",
             "creator_reach_total")
    return {
        "streams":    f.get("streams_total") or f.get("spotify_streams_total") or 0,
        "popularity": f.get("popularity_current") or f.get("spotify_popularity_current") or 0,
        "playlists":  f.get("playlists_total") or f.get("playlists_current") or 0,
        "tiktok":     f.get("creator_reach_total") or 0,
    }


_SPOTIFY_RE = re.compile(r"open\.spotify\.com/track/([A-Za-z0-9]{20,})")


def extract_spotify(raw):
    """Find a Spotify track id anywhere in a Songstats response and return (id, url).

    Handles the common shapes (a links array of {source,url}, a source-tagged object
    with an external_id, or a bare open.spotify.com URL string). Returns ("","") if none.
    """
    sid = ""

    def walk(o):
        nonlocal sid
        if sid:
            return
        if isinstance(o, dict):
            if str(o.get("source", "")).lower() == "spotify":
                cand = o.get("external_id") or o.get("id") or ""
                if re.fullmatch(r"[A-Za-z0-9]{20,}", str(cand)):
                    sid = str(cand)
                if not sid:
                    m = _SPOTIFY_RE.search(str(o.get("url") or o.get("link") or ""))
                    if m:
                        sid = m.group(1)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            m = _SPOTIFY_RE.search(o)
            if m:
                sid = m.group(1)

    walk(raw)
    return sid, (f"https://open.spotify.com/track/{sid}" if sid else "")
