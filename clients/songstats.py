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
    # no source filter — return the full cross-platform stats array
    return _get("tracks/stats", isrc=isrc)


def track_info(isrc):
    """Cross-platform metadata incl. the aggregated track links (Spotify, Apple, ...)."""
    return _get("tracks/info", isrc=isrc)


def _num_in(d, *needles):
    """Largest numeric value in dict `d` whose key matches a needle. Coerces numeric
    STRINGS too — Songstats returns some values as strings, e.g. streams_total '76363.0'."""
    best = 0
    for k, v in (d or {}).items():
        kl = str(k).lower()
        if not any(n in kl for n in needles):
            continue
        try:
            best = max(best, int(float(v)))
        except (TypeError, ValueError):
            continue
    return best


def _stat_sources(raw):
    """Collect every {source, data} stats block anywhere in a Songstats response."""
    out = []

    def find(o):
        if isinstance(o, dict):
            if "source" in o and isinstance(o.get("data"), dict):
                out.append(o)
            for v in o.values():
                find(v)
        elif isinstance(o, list):
            for v in o:
                find(v)
    find(raw)
    return out


def parse_market(raw):
    """Headline market numbers from /tracks/stats.

    Field names vary by source/plan, so we match by substring across every
    {source, data} block, prefer Spotify, and fall back to whichever platform
    reports a value. This stops streams/popularity from silently coming back 0.
    """
    by = {}
    for s in _stat_sources(raw):
        d = s.get("data", {})
        by[str(s.get("source", "")).lower()] = {
            "streams":    _num_in(d, "stream"),
            "popularity": _num_in(d, "popularity", "rating"),
            "playlists":  _num_in(d, "playlist"),
            "reach":      _num_in(d, "creator_reach", "views", "shazam"),
        }
    sp = by.get("spotify", {})
    pick = lambda key: sp.get(key) or max([v.get(key, 0) for v in by.values()] + [0])
    return {
        "streams":    pick("streams"),
        "popularity": pick("popularity"),
        "playlists":  pick("playlists"),
        "tiktok":     by.get("tiktok", {}).get("reach") or pick("reach"),
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
