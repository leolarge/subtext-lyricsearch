# SUBTEXT — MVP (Musixmatch + Mistral + Songstats)

Lyric-context song search: type what a song should be *about* and get tracks ranked by
meaning — including the subtext the title and lyrics don't state. Three APIs, joined by ISRC.

Packaged to **import into Replit with no Agent work** — the `.replit` config is already
correct, so you add three Secrets and press **Run**. That's the credit-saver: the Agent never
has to scaffold or fix anything.

---

## Import into Replit (cheap path — no Agent)

1. Push this folder to GitHub → **Create App → Import from GitHub** (or drag the files into a blank Python Repl).
2. **Secrets** (lock icon):
   - `MUSIXMATCH_API_KEY` (Pro key) · `MISTRAL_API_KEY` · `SONGSTATS_API_KEY`
   - optional cost knob: `MISTRAL_MODEL=mistral-small-latest` (full lyrics are sent by default)
3. Press **Run**. The `.replit` runs `uvicorn main:app --host 0.0.0.0 --port 5000` and opens the web view.

Your **52 enriched songs** ship in `data/index.json`, so it works on Run. **Do not** let the Agent "set up" the project — it's already set up.

---

## Security: the scan finding is NOT in this app

Replit's dependency scan flagged `vite`, `@babel/core`, `markdown-it`, `js-yaml`, `qs`. **None of
these are in your app.** Your app is pure Python (fastapi, uvicorn, httpx, mistralai, gunicorn) —
there is no `package.json`. Those JavaScript packages come from Replit's auto-generated `.local/`
agent skill templates, which the scanner walks. This clean repo **strips `.local/` entirely and
`.gitignore`s it**, and has no JS dependencies, so a scan of the fresh import has nothing to flag.

- **Don't press "Fix with Agent"** on the old project — it would burn credits trying to bump
  versions inside template files you don't ship or control.
- The deployed app (`gunicorn main:app`) never loads any of those packages.

If a fresh Repl re-creates `.local/` and the scan flags it again, that's Replit's own tooling, not
your code — safe to ignore for your deployable app.

---

## The catalog (curated sync core + path to 2,000)

`data/catalog.csv` ships with **~276 hand-picked, real, sync-relevant songs** — trailer staples,
prestige-TV needle-drops, classic licensables, and ad anthems (Pixies, Bon Iver, Lord Huron,
Cinematic Orchestra, Nina Simone, CCR, M83, Hozier, and so on), correctly attributed. Your 52
already-enriched songs are preserved on top.

To reach **2,000**, run the seeder once — it tops the catalog up with real chart tracks (with
ISRCs) across 40 markets, de-duplicated against the curated core:
```bash
python seed_catalog.py   # fills catalog.csv toward 2,000 real songs
python enrich.py         # enriches only NEW songs; existing ones are skipped
```

A note on honesty: those seeded tracks are real and correctly attributed, but they're *popular*
songs, not specifically *sync placements* — there's no API in this stack that returns "songs used
in film/TV." The 276 curated rows are the genuine sync core; the seeder fills volume. For a true
sync-placement list, you'd pull from a sync library / Tunefind-style source.

**Cost reality at 2,000:** enrichment now sends full lyrics to `mistral-large`, so 2,000 songs is a
real spend and many hours with rate-limit backoff. For the hackathon you almost certainly don't
need all 2,000 enriched — options:
- enrich a few hundred and grow live with the button during the demo, or
- set `MISTRAL_MODEL=mistral-small-latest` in Secrets for the bulk run (much cheaper), keeping
  large only if you want maximum subtext nuance.

## Grow the catalog (button + background job)

There's a **Grow catalog +50** button in the UI. It calls `POST /grow`, which enriches the next
50 not-yet-indexed songs **in a background thread** (auto-seeding more from charts if the catalog
is exhausted) and reports live progress via `GET /grow/status`. The button shows a progress bar,
stays disabled while running, and refreshes results when done. Because enriching is slow (live API
calls), it's chunked at 50 per click — press it again to keep growing.

To bulk-grow from the Shell instead:
```bash
python seed_catalog.py   # fills catalog.csv toward 2,000 real songs (with ISRCs)
python enrich.py         # enriches only NEW songs; existing ones are skipped
```
Both are incremental and save after every track. The index hot-reloads on change, so search picks
up new songs without a restart.

---

## Search parameters (genre · mood · meaning)

The brief is parsed by Mistral into **themes, moods, genres, and meaning keywords**, and ranking
blends all of them: theme overlap, an extended-meaning match (your keywords vs each song's true
subject + subtext + scene + tags), mood overlap, and genre. Dimensions you don't mention are
ignored, not penalized. The UI shows how it read your brief ("reading as: genre · mood · theme"),
so a search like *"upbeat indie songs secretly about heartbreak"* filters on indie + upbeat while
ranking by the hidden-heartbreak meaning.

## Monthly cap + which free LLM to use

**A hard cap of 500 new songs/month** is built in (`budget.py`). Each enrichment counts once;
Spotify backfills and searches don't. The ledger auto-resets each month, the **Grow** button
shows `used/cap this mo` and disables itself at the cap, and `enrich.py` stops when the month's
budget is spent. Change it with `MONTHLY_ENRICH_CAP` in Secrets.

**Is Mistral the right free API here?** For 500 songs/month — yes, you don't need to switch.
Mistral's free "Experiment" tier gives rate-limited access to all models (including Large) with a
generous monthly token quota; 500 enrichments sits well inside it. The only pain is its **request
rate** — bursts hit 429s (that's the 15s backoff in `llm.py`), so a batch trickles rather than
sprints. Quality is high, so for a capped catalog it's a fine default.

**If you outgrow it or the throttling annoys you,** the most generous *permanent* free API tier in
2026 is **Google Gemini Flash** — about 15 requests/min and ~1,500 requests/day, which would run a
500-song batch in well under a day with little throttling, and it's strong at JSON. **Groq** (free,
very fast, open models like Llama 3.3 70B) is a good second for speed. Either is an easy swap: keep
the same `infer_context` / `compile_brief` JSON contract and replace the client in `llm.py`
(Gemini's `response_mime_type="application/json"` maps directly to the JSON mode you already use).

**Suggested growth cadence (free Mistral):** let the 500/month cap be your speed limit. Grow in a
few **+50** clicks (or one `enrich.py` run) whenever you have time; the rate-limit backoff means a
batch takes a little while, so kick it off and let it trickle. Set `MISTRAL_MODEL=mistral-small-latest`
for the bulk passes to stretch the free quota further, keeping `large` only for a hero set. At
500/month you add ~6k high-quality songs a year without ever touching a paid tier — and if you need
to go faster, that's the moment to point `llm.py` at Gemini Flash.

## Where your keys burn — and the OpenAI question

**The spend is almost entirely Mistral, during enrichment.** Every song = one `infer_context`
call with the full lyrics in the prompt; 2,000 songs = 2,000 of those. Search is one tiny `compile_brief`
call, now **cached**, so repeat searches cost nothing. Musixmatch/Songstats are quota-based lookups,
not the bottleneck.

**Adding OpenAI to "split the load" does NOT lower cost** — you'd still run the same number of
inferences, just paid across two vendors, plus a second key and integration to maintain. It only
helps **throughput** if you're hitting Mistral's rate limits (429s) during a big enrichment run.

Cheaper levers (already wired via env vars — no code change):
1. **`MISTRAL_MODEL=mistral-small-latest`** — ~5–10x cheaper per call; great for bulk enrichment.
   Keep large only if you want maximum subtext nuance.
2. **Full lyrics are sent by default** so late-verse reveals are caught. Set `MAX_LYRIC_CHARS=1600`
   only if you want to cap input tokens — it trades away meanings that surface in the final lines.
3. **Enrich only what you need** — a sharp 200–400 song catalog demos just as well as 2,000.
4. **Incremental + cache** (built in) — you never re-pay for a song or a repeated search.

Reach for a second provider only if rate limits (not cost) are blocking a time-boxed enrichment run;
even then, raising your Mistral tier is usually simpler than integrating OpenAI.

---

## Files

| File | Role |
|---|---|
| `.replit` / `replit.nix` | Replit run + deploy config (port 5000, gunicorn) — **don't edit** |
| `seed_catalog.py` | top `catalog.csv` up toward 2,000 from Musixmatch charts |
| `enrich.py` | build/grow `index.json` (incremental; backfills Spotify links; instrumental fixed) |
| `grow.py` | background batch enrichment behind the Grow button |
| `clients/musixmatch.py` | resolve track, full lyrics, explicit/genre, ISRC |
| `clients/songstats.py` | market stats + Spotify link extraction |
| `llm.py` | Mistral: `infer_context()` + `compile_brief()` (model + lyric cap via env) |
| `engine.py` | rank index vs brief (cached, hot-reloads on growth) |
| `main.py` | FastAPI: `/search`, `/health`, `/grow`, `/grow/status`, serves the UI |
| `static/index.html` | UI: search, Spotify player, Grow button + progress |

---

## One thing to confirm against live data

`clients/songstats.py` parses the Spotify link and the streams/popularity/playlist fields
**defensively** (Songstats' JSON shape varies by plan). After your first enrich run, open one
record in `data/index.json` — if `spotify_url` is empty or a market number is 0, check a real
Songstats response and adjust the key names in `parse_market` / `extract_spotify`. Songstats also
warms up on the first request per ISRC.
