"""SUBTEXT API — Phase 1 (Musixmatch + Mistral + Songstats).

Run (Replit uses port 5000):  uvicorn main:app --host 0.0.0.0 --port 5000
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import engine
import grow
import budget

app = FastAPI(title="SUBTEXT")


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


# serve the frontend (static/index.html) at /
app.mount("/", StaticFiles(directory="static", html=True), name="static")
