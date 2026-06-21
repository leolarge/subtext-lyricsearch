"""Mistral — the brain.

infer_context(): reads lyrics and infers what a song is REALLY about (subtext),
plus themes, mood, and content/safety flags.
compile_brief(): turns a search brief into target themes for ranking.

Uses JSON mode (response_format=json_object) for reliability.
Docs: https://docs.mistral.ai
"""
import json
import os
import time

# resilient import — works across mistralai SDK layouts
try:
    from mistralai import Mistral
except Exception:  # pragma: no cover
    from mistralai.client import Mistral

from config import MISTRAL_API_KEY

client = Mistral(api_key=MISTRAL_API_KEY)
# Model is env-configurable: set MISTRAL_MODEL=mistral-small-latest to cut per-call cost ~5-10x.
# Full lyrics are sent by default — a song's true meaning can surface only in the final lines.
# Set MAX_LYRIC_CHARS>0 only if you want to cap input tokens (trades away late-verse reveals).
MODEL = os.environ.get("MISTRAL_MODEL", "mistral-large-latest")
# Search compiles a simple brief, so it runs on a fast small model by default (big latency win).
BRIEF_MODEL = os.environ.get("MISTRAL_SEARCH_MODEL", "mistral-small-latest")
MAX_LYRIC_CHARS = int(os.environ.get("MAX_LYRIC_CHARS", "0"))

_FLAGS = ["profanity", "drugs", "alcohol", "violence", "sex", "politics", "religion"]


def _json(system, user, max_tokens=900, retries=4, model=None):
    delay = 15
    for attempt in range(retries):
        try:
            resp = client.chat.complete(
                model=model or MODEL,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=max_tokens,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            if "429" in str(e) and attempt < retries - 1:
                print(f"  rate limited — waiting {delay}s (attempt {attempt+1}/{retries})")
                time.sleep(delay)
                delay *= 2
            else:
                raise


# ---------------------------------------------------------------- lyric context
LYRIC_SYS = """You interpret song lyrics for a music-supervision tool.
Infer what the song is REALLY about, including subtext the lyrics never state outright.
Do NOT just paraphrase. If the meaning is ambiguous, give your best inference and lower confidence.
Read the WHOLE lyric: the true subject is sometimes revealed only in the final verse or last lines.
Crucially: flag sensitive content even when it is implied rather than named — e.g. a love song
whose true subject is addiction should set safety_flags.drugs = true.

Return ONLY a JSON object with EXACTLY these keys:
{
  "literal": "<one phrase: what the words literally describe>",
  "trueSubject": "<one phrase: what it is actually about>",
  "subtext": "<one sentence: the implied meaning>",
  "scenario": "<one phrase: the implied scene or situation>",
  "themes": ["<up to 5 short lowercase theme words>"],
  "lyricMood": ["<emotional tone of the words, e.g. defiant, mournful, joyful>"],
  "sentiment": <number -1 to 1>,
  "confidence": <number 0 to 1: how confident you are in the inference>,
  "divergent": <true if the surface meaning differs from the true subject, else false>,
  "safety_flags": {"profanity": bool, "drugs": bool, "alcohol": bool, "violence": bool, "sex": bool, "politics": bool, "religion": bool}
}"""


def _blank():
    return {
        "literal": "", "trueSubject": "", "subtext": "", "scenario": "",
        "themes": [], "lyricMood": [], "sentiment": 0.0, "confidence": 0.0,
        "divergent": False, "safety_flags": {k: False for k in _FLAGS},
    }


def infer_context(title, artist, lyrics, instrumental=False):
    blank = _blank()
    # only call a track instrumental if Musixmatch explicitly says so
    if instrumental:
        blank["subtext"] = "Instrumental — no lyrics to interpret."
        return blank
    # vocal track but lyrics didn't come back: say so, don't mislabel as instrumental
    if not (lyrics or "").strip():
        blank["subtext"] = "Lyrics unavailable — meaning not analyzed."
        return blank
    clip = lyrics.strip()
    if MAX_LYRIC_CHARS > 0:
        clip = clip[:MAX_LYRIC_CHARS]
    try:
        out = _json(LYRIC_SYS, f"Title: {title}\nArtist: {artist}\nLyrics:\n{clip}")
    except Exception as e:
        print("  ! mistral infer_context failed:", e)
        return blank
    out = {**blank, **out}
    out["safety_flags"] = {**blank["safety_flags"], **(out.get("safety_flags") or {})}
    return out


# ---------------------------------------------------------------- brief compiler
BRIEF_SYS = """Convert a music-search brief into JSON with EXACTLY these keys:
{
  "target_themes": ["lowercase subject/theme words the song should be ABOUT, including implied subtext"],
  "target_moods":  ["emotional tone words requested (e.g. upbeat, melancholy, defiant); [] if unspecified"],
  "target_genres": ["genre words requested (e.g. indie, hip-hop, folk, country); [] if unspecified"],
  "keywords":      ["3-8 salient content words (topics, objects, feelings) to match against a song's meaning"],
  "meaning": "one-line restatement of the emotional/subject target",
  "clean_only": false
}
Read natural language for ALL dimensions. Example:
"upbeat indie songs that are secretly about heartbreak" ->
  target_moods:["upbeat"], target_genres:["indie"], target_themes:["heartbreak"],
  keywords:["heartbreak","hidden","sadness","party"]
Set clean_only true only if the brief asks for clean / family-friendly / no-explicit.
Return ONLY the JSON object."""


def compile_brief(brief):
    try:
        # fast small model + fail-fast: a rate-limited search returns instantly via the
        # graceful fallback below instead of hanging on the 15s backoff.
        spec = _json(BRIEF_SYS, brief, max_tokens=350, retries=1, model=BRIEF_MODEL)
    except Exception as e:
        print("  ! mistral compile_brief failed:", e)
        return {"target_themes": [], "target_moods": [], "target_genres": [],
                "keywords": [], "meaning": brief, "clean_only": False}
    spec.setdefault("target_themes", [])
    spec.setdefault("target_moods", [])
    spec.setdefault("target_genres", [])
    spec.setdefault("keywords", [])
    spec.setdefault("meaning", brief)
    spec.setdefault("clean_only", False)
    return spec
