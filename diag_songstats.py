import json, httpx
from config import SONGSTATS_API_KEY

BASE = "https://api.songstats.com/enterprise/v1"
HEAD = {"apikey": SONGSTATS_API_KEY, "Accept": "application/json"}

def call(path, **params):
    try:
        r = httpx.get(f"{BASE}/{path}", headers=HEAD, params=params, timeout=30)
        return r.status_code, r.text
    except Exception as e:
        return None, repr(e)

print("key present:", bool(SONGSTATS_API_KEY), "| length:", len(SONGSTATS_API_KEY or ""))

sc, body = call("info/status")
print(f"\n[info/status] HTTP {sc}\n{body[:400]}")

idx = json.load(open("data/index.json"))
isrcs = [t.get("isrc") for t in idx if t.get("isrc")]
print(f"\ncatalog: {len(idx)} songs, {len(isrcs)} have an ISRC")
if not isrcs:
    print("!! No ISRCs in the catalog — Songstats looks up by ISRC, so nothing can load.")
    raise SystemExit

isrc = isrcs[0]
print(f"testing ISRC: {isrc}")
for path in ("tracks/stats", "tracks/info"):
    sc, body = call(path, isrc=isrc)
    print(f"\n[{path}?isrc={isrc}] HTTP {sc}\n{body[:1200]}")
