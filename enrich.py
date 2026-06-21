"""Pipeline A — build/grow the searchable index.

For each row in data/catalog.csv:
  Musixmatch -> resolve track + full lyrics + explicit/genre + ISRC
  Mistral    -> infer context (true subject, subtext, themes, safety flags)
  Songstats  -> market stats + the Spotify link, keyed by ISRC
Writes data/index.json.

Credit-friendly:
  * already-enriched songs are skipped (matched by title+artist)
  * if an existing song is just missing its Spotify link, it's backfilled with a
    single cheap Songstats call — NO Mistral spend
  * progress is written after every track, so a crash never loses work

Run:  python enrich.py
catalog columns:  isrc,title,artist   (isrc optional — Musixmatch returns it from the name)
"""
import csv, json, pathlib, sys, time
import llm
import budget
from clients import musixmatch, songstats


def _spotify_for(isrc, raw_stats=None):
    """Return (id, url). Try the stats response first, then /tracks/info."""
    sid, url = songstats.extract_spotify(raw_stats or {})
    if not sid and isrc:
        sid, url = songstats.extract_spotify(songstats.track_info(isrc))
    return sid, url


def build_one(row):
    isrc = (row.get("isrc") or "").strip()
    title = (row.get("title") or "").strip()
    artist = (row.get("artist") or "").strip()

    # 1) resolve + lyrics (Musixmatch)
    tr = musixmatch.match_by_isrc(isrc) if isrc else None
    if not tr:
        tr = musixmatch.match_by_name(title, artist)
    if not tr:
        print("  no Musixmatch match:", title, "—", artist)
        return None
    isrc = isrc or tr.get("isrc", "")

    instrumental = bool(tr["instrumental"])      # FIX: trust only Musixmatch's explicit flag
    lyr = {"body": "", "language": "", "explicit": False}
    if tr["commontrack_id"] and not instrumental:
        lyr = musixmatch.get_lyrics(tr["commontrack_id"])

    # 2) context (Mistral)
    ctx = llm.infer_context(tr["title"], tr["artist"], lyr["body"], instrumental)

    # 3) market + Spotify link (Songstats) — needs an ISRC
    raw_stats = songstats.track_stats(isrc) if isrc else {}
    market = songstats.parse_market(raw_stats)
    spotify_id, spotify_url = _spotify_for(isrc, raw_stats)

    explicit = tr["explicit"] or lyr["explicit"] or ctx["safety_flags"].get("profanity", False)

    return {
        "id": isrc or str(tr["commontrack_id"]), "isrc": isrc,
        "title": tr["title"], "artist": tr["artist"],
        "genre": tr["genre"] or "—",
        "lang": (lyr["language"] or "").upper() or "—",
        "year": tr["year"] or "",
        "instrumental": instrumental,
        "spotify_id": spotify_id, "spotify_url": spotify_url,
        # context (Mistral)
        "literal": ctx["literal"], "trueSubject": ctx["trueSubject"],
        "subtext": ctx["subtext"], "scenario": ctx["scenario"],
        "themes": ctx["themes"], "lyricMood": ctx["lyricMood"],
        "sentiment": ctx["sentiment"], "confidence": ctx["confidence"],
        "divergent": ctx["divergent"],
        "explicit": bool(explicit), "safety": ctx["safety_flags"],
        # market (Songstats)
        "streams": market["streams"], "pop": market["popularity"],
        "playlists": market["playlists"], "tiktok": market["tiktok"],
        "momentum": round((market["popularity"] or 0) / 100, 2),
        "gem": (market["streams"] or 0) < 250_000,
        "match": 0,
    }


def backfill(rec):
    """Cheap top-ups for an already-enriched record — NO Mistral.
    Adds a Spotify link if missing, and refreshes market stats if they came back
    empty the first time (e.g. Songstats was still warming up)."""
    changed = False
    isrc = rec.get("isrc", "")
    need_market = (rec.get("streams", 0) or 0) == 0 and (rec.get("pop", 0) or 0) == 0
    need_spotify = not rec.get("spotify_url")
    raw_stats = songstats.track_stats(isrc) if isrc and (need_market or need_spotify) else {}

    if need_market and raw_stats:
        m = songstats.parse_market(raw_stats)
        if m["streams"] or m["popularity"] or m["playlists"]:
            rec["streams"], rec["pop"] = m["streams"], m["popularity"]
            rec["playlists"], rec["tiktok"] = m["playlists"], m["tiktok"]
            rec["momentum"] = round((m["popularity"] or 0) / 100, 2)
            rec["gem"] = (m["streams"] or 0) < 250_000
            changed = True
    if need_spotify:
        sid, url = _spotify_for(isrc, raw_stats)
        if sid:
            rec["spotify_id"], rec["spotify_url"] = sid, url
            changed = True
    return changed


def run(catalog="data/catalog.csv", out="data/index.json"):
    rows = list(csv.DictReader(open(catalog, encoding="utf-8")))
    pathlib.Path("data").mkdir(exist_ok=True)
    out_path = pathlib.Path(out)

    idx = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else []
    by_key = {(t["title"].lower(), t["artist"].lower()): t for t in idx}

    def save():
        out_path.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")

    added = patched = 0
    for i, r in enumerate(rows):
        title = (r.get("title") or "").strip()
        artist = (r.get("artist") or "").strip()
        key = (title.lower(), artist.lower())
        existing = by_key.get(key)

        if existing:
            if backfill(existing):     # spotify link + market refresh, no Mistral spend
                patched += 1
                save()
                print(f"[{i+1}/{len(rows)}] +refresh: {title} — {artist}")
            else:
                print(f"[{i+1}/{len(rows)}] skip: {title} — {artist}")
            sys.stdout.flush()
            continue

        if budget.remaining() <= 0:
            print(f"\nmonthly cap reached ({budget.CAP} new songs) — stopping. Resets next month.")
            break
        try:
            t = build_one(r)
            if t:
                idx.append(t)
                by_key[key] = t
                added += 1
                budget.consume(1)
                save()
                print(f"[{i+1}/{len(rows)}] ok: {t['title']} — {t['artist']} | {t['trueSubject'] or 'instrumental'}")
        except Exception as e:
            print(f"[{i+1}/{len(rows)}] FAIL: {title} — {e}")
        sys.stdout.flush()
        if i < len(rows) - 1:
            time.sleep(2)

    print(f"\ndone — {added} new, {patched} spotify-backfilled, {len(idx)} total -> {out}")
    print(f"monthly budget: {budget.used()}/{budget.CAP} used, {budget.remaining()} left")


if __name__ == "__main__":
    run()
