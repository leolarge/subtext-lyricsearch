"""Grow data/catalog.csv to 1,000+ real songs from Musixmatch charts.

Pulls the top charts across many markets (lyrics-only), de-duplicates, and appends
to your existing catalog without disturbing the songs already there. Run once with
your Musixmatch Pro key, then run enrich.py to enrich the new rows.

Run:  python seed_catalog.py
"""
import csv, pathlib, sys, time
from clients import musixmatch

TARGET = 2000        # stop once the catalog reaches this many unique songs
PAGES_PER_MARKET = 3 # 100 per page
CHARTS = ["top", "hot"]
MARKETS = ["us", "gb", "de", "fr", "ca", "au", "br", "mx", "es", "it",
           "nl", "se", "pl", "jp", "kr", "in", "za", "ar", "ie", "nz",
           "be", "at", "ch", "pt", "gr", "cz", "hu", "ro", "fi", "dk",
           "no", "cl", "co", "pe", "tr", "ph", "id", "my", "th", "vn"]


def _chart_page(country, page, chart="top"):
    body = musixmatch._get("chart.tracks.get", chart_name=chart, page=page,
                           page_size=100, country=country, f_has_lyrics=1)
    rows = []
    for item in (body.get("track_list") or []):
        t = item.get("track") or {}
        title = (t.get("track_name") or "").strip()
        artist = (t.get("artist_name") or "").strip()
        if title and artist:
            rows.append({"isrc": t.get("track_isrc", "") or "", "title": title, "artist": artist})
    return rows


def run(path="data/catalog.csv"):
    pathlib.Path("data").mkdir(exist_ok=True)
    p = pathlib.Path(path)

    seen, rows = set(), []
    if p.exists():
        for r in csv.DictReader(open(path, encoding="utf-8")):
            k = ((r.get("title") or "").lower(), (r.get("artist") or "").lower())
            if k[0] and k not in seen:
                seen.add(k)
                rows.append({"isrc": r.get("isrc", "") or "", "title": r["title"], "artist": r["artist"]})
    print(f"starting from {len(rows)} existing songs")

    for chart in CHARTS:
        if len(rows) >= TARGET:
            break
        for country in MARKETS:
            if len(rows) >= TARGET:
                break
            for page in range(1, PAGES_PER_MARKET + 1):
                if len(rows) >= TARGET:
                    break
                try:
                    items = _chart_page(country, page, chart)
                except Exception as e:
                    print(f"  {chart}/{country} p{page}: failed ({e})")
                    continue
                new = 0
                for it in items:
                    k = (it["title"].lower(), it["artist"].lower())
                    if k not in seen:
                        seen.add(k)
                        rows.append(it)
                        new += 1
                print(f"{chart}/{country} p{page}: +{new} (total {len(rows)})")
                sys.stdout.flush()
                time.sleep(1)

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["isrc", "title", "artist"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {len(rows)} songs -> {path}\nnow run:  python enrich.py")


if __name__ == "__main__":
    run()
