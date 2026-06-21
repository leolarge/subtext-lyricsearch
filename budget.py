"""Monthly enrichment budget — a hard cap on NEW songs enriched per calendar month.

Each successful enrichment = one Mistral call, so it counts against the cap.
Spotify backfills and searches do NOT count (a backfill is no-LLM; search is one tiny
cached call). The ledger auto-resets when the month changes.
Change the limit with MONTHLY_ENRICH_CAP in Secrets (default 500).
"""
import json
import os
import pathlib
import datetime

LEDGER = pathlib.Path("data/enrich_ledger.json")
CAP = int(os.environ.get("MONTHLY_ENRICH_CAP", "500"))


def _month():
    return datetime.date.today().strftime("%Y-%m")


def _read():
    if LEDGER.exists():
        try:
            d = json.loads(LEDGER.read_text(encoding="utf-8"))
            if d.get("month") == _month():
                return d
        except Exception:
            pass
    return {"month": _month(), "count": 0}


def used():
    return _read().get("count", 0)


def remaining():
    return max(0, CAP - used())


def consume(n=1):
    pathlib.Path("data").mkdir(exist_ok=True)
    d = _read()
    d["count"] = d.get("count", 0) + n
    LEDGER.write_text(json.dumps(d), encoding="utf-8")


def status():
    u = used()
    return {"month": _month(), "used": u, "cap": CAP, "remaining": max(0, CAP - u)}
