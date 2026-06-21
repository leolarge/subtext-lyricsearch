"""Background catalog growth — enrich more songs without blocking the web request.

start(count) launches a background thread that enriches up to `count` not-yet-indexed
songs from data/catalog.csv (auto-seeding more from charts if the catalog is exhausted).
Progress is written to data/grow_status.json so /grow/status works across gunicorn workers.
"""
import csv, json, pathlib, threading, time
import enrich
import engine
import budget

STATUS = pathlib.Path("data/grow_status.json")
INDEX_PATH = pathlib.Path("data/index.json")
CATALOG = pathlib.Path("data/catalog.csv")
_lock = threading.Lock()
_STALE = 1800   # seconds; a run older than this is treated as dead


def _set(**d):
    cur = read()
    cur.update(d)
    cur["ts"] = time.time()
    STATUS.write_text(json.dumps(cur), encoding="utf-8")


def read():
    if STATUS.exists():
        try:
            return json.loads(STATUS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"running": False, "added": 0, "i": 0, "n": 0,
            "total": len(engine.INDEX), "message": "idle", "ts": 0}


def _todo():
    rows = list(csv.DictReader(open(CATALOG, encoding="utf-8"))) if CATALOG.exists() else []
    idx = json.loads(INDEX_PATH.read_text(encoding="utf-8")) if INDEX_PATH.exists() else []
    done = {(t["title"].lower(), t["artist"].lower()) for t in idx}
    todo = [r for r in rows
            if (r.get("title") or "").strip()
            and ((r.get("title") or "").lower(), (r.get("artist") or "").lower()) not in done]
    return idx, todo


def _run(count):
    try:
        idx, todo = _todo()
        if not todo:                      # catalog fully enriched -> pull more songs first
            _set(running=True, message="fetching more songs from charts…")
            try:
                import seed_catalog
                seed_catalog.run()
            except Exception as e:
                _set(message=f"couldn't fetch more: {e}")
            idx, todo = _todo()
        rem = budget.remaining()
        if rem <= 0:
            _set(running=False, added=0, i=0, n=0, total=len(idx),
                 message=f"monthly cap reached ({budget.CAP}) — resets next month")
            return
        batch = todo[:min(count, rem)]
        _set(running=True, added=0, i=0, n=len(batch), total=len(idx), message="starting…")
        added = 0
        for i, r in enumerate(batch):
            _set(running=True, added=added, i=i + 1, n=len(batch), total=len(idx) + added,
                 message=f"enriching {(r.get('title') or '')[:40]} — {(r.get('artist') or '')[:30]}")
            try:
                t = enrich.build_one(r)
                if t:
                    idx.append(t)
                    added += 1
                    budget.consume(1)
                    INDEX_PATH.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            time.sleep(1)
        engine.reload()
        _set(running=False, added=added, i=len(batch), n=len(batch),
             total=len(idx), message=f"done — added {added} song(s)")
    finally:
        if _lock.locked():
            _lock.release()


def start(count=50):
    st = read()
    if st.get("running") and (time.time() - st.get("ts", 0)) < _STALE:
        return {"started": False, "running": True}
    if not _lock.acquire(blocking=False):
        return {"started": False, "running": True}
    _set(running=True, added=0, i=0, n=count, message="queued…")
    threading.Thread(target=_run, args=(int(count),), daemon=True).start()
    return {"started": True}
