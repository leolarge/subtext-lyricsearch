"""SUBTEXT API — Phase 1 (Musixmatch + Mistral + Songstats).

Run (Replit uses port 5000):  uvicorn main:app --host 0.0.0.0 --port 5000
"""
import json
import pathlib
import threading
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import engine
import enrich
import grow
import budget

app = FastAPI(title="SUBTEXT")

_INDEX_PATH = pathlib.Path("data/index.json")
_add_lock = threading.Lock()
_add_state: dict = {"running": False, "message": "idle", "result": None, "error": None, "ts": 0}


class Query(BaseModel):
    brief: str


@app.post("/search")
def search(q: Query):
    """Rank the enriched catalog against the brief (Mistral). Returns all tracks
    with match scores; the frontend applies compliance toggles client-side."""
    return engine.search(q.brief)


@app.get("/health")
def health():
    return {"ok": True, "indexed": len(engine.INDEX), "budget": budget.status()}


class GrowReq(BaseModel):
    count: int = 50


@app.post("/grow")
def grow_start(q: GrowReq = GrowReq()):
    """Enrich up to `count` more songs in the background (auto-seeds if catalog is empty)."""
    return grow.start(max(1, min(100, q.count)))


@app.get("/grow/status")
def grow_status():
    return {**grow.read(), "budget": budget.status()}


class AddReq(BaseModel):
    title: str
    artist: str


def _run_add(title: str, artist: str):
    global _add_state
    try:
        idx = json.loads(_INDEX_PATH.read_text(encoding="utf-8")) if _INDEX_PATH.exists() else []
        done = {(t["title"].lower(), t["artist"].lower()) for t in idx}
        if (title.lower(), artist.lower()) in done:
            existing = next(t for t in idx
                            if t["title"].lower() == title.lower()
                            and t["artist"].lower() == artist.lower())
            _add_state = {"running": False, "message": "already in catalog",
                          "result": existing, "error": None, "ts": time.time()}
            return
        _add_state["message"] = f'Looking up "{title}" on Musixmatch\u2026'
        t = enrich.build_one({"title": title, "artist": artist, "isrc": ""})
        if not t:
            _add_state = {"running": False, "message": "No match found on Musixmatch.",
                          "result": None, "error": "no_match", "ts": time.time()}
            return
        idx.append(t)
        _INDEX_PATH.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")
        budget.consume(1)
        engine.reload()
        _add_state = {"running": False, "message": "added",
                      "result": t, "error": None, "ts": time.time()}
    except Exception as e:
        _add_state = {"running": False, "message": str(e),
                      "result": None, "error": "exception", "ts": time.time()}
    finally:
        try:
            _add_lock.release()
        except RuntimeError:
            pass


@app.post("/add")
def add_song(req: AddReq):
    global _add_state
    if not _add_lock.acquire(blocking=False):
        return {"started": False, "running": True}
    _add_state = {"running": True,
                  "message": f'Starting enrichment for "{req.title.strip()}"...',
                  "result": None, "error": None, "ts": time.time()}
    threading.Thread(
        target=_run_add,
        args=(req.title.strip(), req.artist.strip()),
        daemon=True,
    ).start()
    return {"started": True}


@app.get("/add/status")
def add_status():
    return _add_state


# serve the frontend (static/index.html) at /
app.mount("/", StaticFiles(directory="static", html=True), name="static")
