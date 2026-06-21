"""Pipeline B — rank the enriched index against a search brief.

The brief (compiled by Mistral) carries themes, moods, genres, and meaning keywords.
Ranking blends, for each track:
  * theme overlap          (what it's about)
  * extended-meaning match (keywords vs trueSubject + subtext + scenario + tags)
  * mood overlap           (lyric emotional tone)
  * genre match
  * a small confidence weight
Dimensions the brief doesn't specify are simply skipped (no penalty), then re-normalized.

Light-touch perf: per-track lookups are precomputed once, identical briefs are cached
(also avoids a repeat Mistral call), and the index hot-reloads when it grows on disk.
"""
import json
import os
import llm

INDEX_PATH = "data/index.json"


def _norm(s):
    return (s or "").lower()


def _load():
    data = json.load(open(INDEX_PATH, encoding="utf-8")) if os.path.exists(INDEX_PATH) else []
    for t in data:
        t["_themeset"] = set(_norm(x) for x in t.get("themes", []))
        t["_moodset"] = set(_norm(x) for x in t.get("lyricMood", []))
        t["_genre"] = _norm(t.get("genre", ""))
        blob = [t.get("trueSubject", ""), t.get("subtext", ""), t.get("scenario", "")]
        blob += list(t.get("themes", [])) + list(t.get("lyricMood", [])) + [t.get("genre", "")]
        t["_blob"] = " ".join(_norm(p) for p in blob)
    return data


INDEX = _load()
_CACHE = {}
_MTIME = os.path.getmtime(INDEX_PATH) if os.path.exists(INDEX_PATH) else 0

BRAND_RULES = {   # mirrored in the frontend for instant toggles; kept here for reference
    "open": [], "family": ["drugs", "alcohol", "violence", "sex", "profanity"],
    "premium": ["drugs", "profanity"], "wellness": ["drugs", "violence"],
}


def reload():
    """Reload the index from disk and clear caches (called after the catalog grows)."""
    global INDEX, _CACHE, _MTIME
    INDEX = _load()
    _CACHE = {}
    _MTIME = os.path.getmtime(INDEX_PATH) if os.path.exists(INDEX_PATH) else 0


def _maybe_reload():
    global _MTIME
    try:
        m = os.path.getmtime(INDEX_PATH)
    except OSError:
        return
    if m != _MTIME:
        reload()


def score(t, spec):
    themes, moods = spec["themes"], spec["moods"]
    genres, kws = spec["genres"], spec["keywords"]
    parts = []                       # (weight, component_score in 0..1)

    if themes:
        have = t.get("_themeset") or set()
        parts.append((0.40, len(set(themes) & have) / len(themes)))
    if kws:
        blob = t.get("_blob", "")
        hits = sum(1 for k in kws if k and k in blob)
        parts.append((0.35, hits / len(kws)))
    if moods:
        have = t.get("_moodset") or set()
        mh = sum(1 for mm in moods if any(mm in hv or hv in mm for hv in have))
        parts.append((0.15, mh / len(moods)))
    if genres:
        g = t.get("_genre", "")
        gm = 1.0 if any(gg and (gg in g or g in gg) for gg in genres) else 0.0
        parts.append((0.10, gm))

    if parts:
        wsum = sum(w for w, _ in parts)
        base = sum(w * s for w, s in parts) / wsum
    else:
        base = 0.0
    return 0.85 * base + 0.15 * t.get("confidence", 0)


def search(brief):
    _maybe_reload()
    key = _norm(brief).strip()
    if key in _CACHE:
        return _CACHE[key]

    raw_spec = llm.compile_brief(brief)
    spec = {
        "themes":   [x.lower() for x in raw_spec.get("target_themes", [])],
        "moods":    [x.lower() for x in raw_spec.get("target_moods", [])],
        "genres":   [x.lower() for x in raw_spec.get("target_genres", [])],
        "keywords": [x.lower() for x in raw_spec.get("keywords", [])],
        "meaning":  raw_spec.get("meaning", ""),
    }

    ranked = []
    for raw in INDEX:
        t = {k: v for k, v in raw.items() if not k.startswith("_")}   # hide helper fields
        t["match"] = min(99, round(score(raw, spec) * 55) + 44)
        ranked.append(t)
    ranked.sort(key=lambda t: -t["match"])

    res = {"results": ranked, "meaning": spec["meaning"], "themes": spec["themes"],
           "moods": spec["moods"], "genres": spec["genres"], "keywords": spec["keywords"]}
    _CACHE[key] = res
    return res
