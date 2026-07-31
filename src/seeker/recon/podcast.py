"""Podcast transcript lane (FREE + publication-safe) — brief 28.

Two tiers, both free of redistribution problems (unlike Podchaser's ToS):
  1. Podcasting-2.0 `<podcast:transcript>` tag in the open RSS feed — the publisher's OWN published
     transcript (JSON/SRT/VTT/text), no audio processing needed. Cleanest.
  2. Groq-Whisper fallback — download the episode audio and transcribe it ourselves via Groq's
     whisper-large-v3 (uses our EXISTING Groq key; we OWN the output → no third-party redistribution
     ToS). For long episodes Groq's file cap applies; chunking is a follow-up.
Plus YouTube (separate lane, already built). A podcast is a SENSOR — its claims get graded like any
finding (sleuth speculation -> hearsay/unproven unless corroborated, Vera).

Discovery (find feeds by TOPIC) is a follow-up (Podcast Index API, free key). Until then, `gather`
is a harmless no-op and the transcription primitives (transcribe_feed / groq_transcribe) work on any
feed you hand them. NOTE (Cipher): verify the Groq transcriptions endpoint on first real audio.
"""
from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET

import requests

from .. import config
from ..models import Citation
from .extractor import extract

_GROQ_TRANSCRIBE = "https://api.groq.com/openai/v1/audio/transcriptions"
_PI_SEARCH = "https://api.podcastindex.org/api/1.0/search/byterm"
_PODCAST_NS = "{https://podcastindex.org/namespace/1.0}"
_MAX_AUDIO_BYTES = 24_000_000  # Groq file cap (~25MB) — long episodes need chunking (follow-up)


def _strip(text: str) -> str:
    """VTT/SRT/HTML/JSON transcript files -> plain text (best-effort)."""
    if not text:
        return ""
    if text.lstrip().startswith("{") or text.lstrip().startswith("["):
        try:
            import json
            data = json.loads(text)
            segs = data if isinstance(data, list) else data.get("segments") or data.get("body") or []
            out = " ".join(s.get("text", "") if isinstance(s, dict) else str(s) for s in segs)
            if out.strip():
                return out
        except Exception:
            pass
    lines = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln == "WEBVTT" or ln.isdigit() or "-->" in ln:
            continue
        lines.append(re.sub(r"<[^>]+>", "", ln))
    return " ".join(lines)


_TRANSCRIPT_CACHE: dict = {}   # audio_url -> transcript text, memoized per-process (Zara): the same
                               # episode never gets re-downloaded + re-transcribed within one run.


def groq_transcribe(audio_url: str) -> str:
    """Download episode audio and transcribe via Groq whisper-large-v3 (we own the output).

    Long-episode handling WITHOUT ffmpeg: an mp3 is a stream of self-contained frames, so the file
    decodes cleanly *from the front*. We Range-fetch the first ~24MB (the whole file if smaller, else
    the leading chunk) — that always starts on a frame boundary and transcribes reliably (~first
    40-50 min of a typical show). Full multi-chunk coverage needs ffmpeg to split on frame boundaries
    (follow-up); mid-stream byte-chunks don't start on a frame header, so we don't fake them. Returns
    '' on any error."""
    if not config.GROQ_API_KEY:
        return ""
    if audio_url in _TRANSCRIPT_CACHE:
        return _TRANSCRIPT_CACHE[audio_url]
    try:
        a = requests.get(audio_url, timeout=config.REQUEST_TIMEOUT,
                         headers={"Range": f"bytes=0-{_MAX_AUDIO_BYTES - 1}"})
        a.raise_for_status()
        audio = a.content[:_MAX_AUDIO_BYTES]   # leading chunk (or whole file if it fit)
        if not audio:
            return ""
        r = requests.post(
            _GROQ_TRANSCRIBE,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            files={"file": ("episode.mp3", audio, "audio/mpeg")},
            data={"model": "whisper-large-v3", "response_format": "text"},
            timeout=180)
        r.raise_for_status()
        try:
            text = r.json().get("text", "") if r.headers.get("content-type", "").startswith("application/json") else r.text
        except Exception:
            text = r.text
        _TRANSCRIPT_CACHE[audio_url] = text or ""
        return text or ""
    except Exception:
        return ""


def _episode_transcript(item) -> tuple:
    """(title, audio_url, transcript_text_or_None) for one RSS <item>. Prefers the free transcript tag."""
    title = (item.findtext("title") or "").strip()
    tag = item.find(f"{_PODCAST_NS}transcript")
    turl = tag.get("url") if tag is not None else None
    audio = item.find("enclosure")
    aurl = audio.get("url") if audio is not None else None
    text = None
    if turl:
        try:
            resp = requests.get(turl, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            text = _strip(resp.text)
        except Exception:
            text = None
    return title, aurl, (text or None)


def _within_recency(item, recency_years: int | None) -> bool:
    """True if the episode's <pubDate> is within recency_years (or if unbounded / undated).
    Undated episodes pass (absence of a date is not evidence of age)."""
    if not recency_years:
        return True
    raw = (item.findtext("pubDate") or "").strip()
    if not raw:
        return True
    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        pub = parsedate_to_datetime(raw)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - pub).days
        return age_days <= recency_years * 366
    except Exception:
        return True


def _episode_text(item) -> str:
    """Title + description/summary of an RSS <item>, lowercased — for cheap episode-level relevance."""
    bits = []
    for tag in ("title", "description", "{http://purl.org/rss/1.0/modules/content/}encoded",
                "{http://www.itunes.com/dtds/podcast-1.0.dtd}summary",
                "{http://www.itunes.com/dtds/podcast-1.0.dtd}subtitle"):
        el = item.find(tag)
        if el is not None and el.text:
            bits.append(el.text)
    return re.sub(r"<[^>]+>", " ", " ".join(bits)).lower()


def _episode_matches(item, match_tokens: set) -> bool:
    """Does this episode's title/description mention the actual case? The whole reason the podcast lane
    came back empty: byterm finds genre-right SHOWS, but the case lives in ONE episode. We keep an
    episode only if its metadata shares a case-specific token (a name/place/specific), so we transcribe
    signal, not a genre show's back-catalogue. Empty token set -> keep (legacy behaviour)."""
    if not match_tokens:
        return True
    text = _episode_text(item)
    return any(tok in text for tok in match_tokens)


def transcribe_feed(feed_url: str, question: str, *, max_eps: int = 3,
                    branch_id: str = "main", recency_years: int | None = None,
                    match_tokens: set | None = None) -> tuple:
    """Pull transcripts for a podcast's recent episodes (RSS transcript tag first, else Groq-Whisper),
    extract findings vs the question. `recency_years` bounds how far back to read (case-adaptive:
    tight for active cases, wide/None for old cold cases). `match_tokens`: keep only episodes whose
    title/description mentions the case (episode-level relevance — the fix for genre-show discovery).
    Returns (findings, transcripts). Fail-open."""
    try:
        r = requests.get(feed_url, timeout=config.REQUEST_TIMEOUT,
                         headers={"User-Agent": "Seeker/1.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return [], []
    findings, transcripts = [], []
    recent = [it for it in root.findall(".//item") if _within_recency(it, recency_years)]
    # Episode-level relevance: scan ALL recent episodes, then cap only the EXPENSIVE step.
    # Matching is a free in-memory string check on RSS we already fetched, so capping the SCAN is
    # pure loss — and it silently killed the lane (fix 2026-07-21): a show with 1000+ recent episodes
    # had its 7 on-topic episodes ("Strange Cases of MISSING SCIENTISTS", "...Disappearance of Monica
    # Reza") sitting well past the old 40-episode window, so the podcast lane read DEAD while the
    # coverage was right there. Cheap filter over everything; transcription stays bounded by max_eps.
    matched = [it for it in recent[:2000] if _episode_matches(it, match_tokens or set())]
    items = matched[:max_eps]
    for item in items:
        title, aurl, text = _episode_transcript(item)
        if not text and aurl:
            text = groq_transcribe(aurl) or None   # tier 2: transcribe ourselves
        if not text or len(text) < 200:
            continue
        url = aurl or feed_url
        transcripts.append({"url": url, "title": title, "text": text})
        findings.extend(extract(question, text, Citation(url=url, title=title,
                                                         source_type="podcast"),
                                branch_id=branch_id))
    return findings, transcripts


def search_feeds(term: str, *, max_feeds: int = 3) -> list:
    """Podcast Index (FREE) discovery: find podcast feeds relevant to a topic. Returns
    [{"url","title"}]. Auth = sha1(apiKey + apiSecret + unixTime) per the API. Empty if no key."""
    if not (config.PODCASTINDEX_API_KEY and config.PODCASTINDEX_API_SECRET):
        return []
    try:
        t = str(int(time.time()))
        h = hashlib.sha1((config.PODCASTINDEX_API_KEY + config.PODCASTINDEX_API_SECRET + t)
                         .encode()).hexdigest()
        r = requests.get(_PI_SEARCH, params={"q": term, "max": max_feeds},
                         headers={"User-Agent": "Seeker/1.0", "X-Auth-Key": config.PODCASTINDEX_API_KEY,
                                  "X-Auth-Date": t, "Authorization": h},
                         timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        feeds = (r.json() or {}).get("feeds", []) or []
        return [{"url": f.get("url", ""), "title": f.get("title", ""),
                 "desc": f.get("description", ""), "author": f.get("author", "")}
                for f in feeds if f.get("url")][:max_feeds]
    except Exception:
        return []


_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_STOPWORDS = {"what", "who", "when", "where", "why", "how", "happened", "the", "a", "an",
              "of", "to", "in", "on", "is", "was", "did", "do", "does", "case", "cold",
              "unsolved", "mystery", "theories", "theory", "evidence", "disappearance",
              "murder", "death", "investigation", "and", "or", "about"}


def _search_terms(question: str) -> list:
    """Distill a verbose QUESTION into SEVERAL candidate discovery phrases, specific -> general.

    `byterm` matches feed titles literally, so one term misses coverage: a case is titled after both
    the PERSON ('Monica Reza') and the TOPIC ('missing scientists'). Asking for 2-3 phrases catches
    the dedicated-person show AND the topical show. LLM first (JSON list), heuristic fallback. The
    caller relevance-filters results, so a slightly-broad phrase here is safe."""
    q = (question or "").strip()
    if not q:
        return []
    terms = []
    try:
        from .. import ratelimit
        import json as _json
        resp = ratelimit.post(
            "openrouter", _OPENROUTER_URL,
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.EXTRACTOR_MODEL,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "user", "content":
                      "A podcast about this case might be titled after the PERSON, the TOPIC, or the "
                      "PLACE. Give 2-3 short (2-4 word) search phrases to find such shows, most "
                      "specific first. No punctuation.\n\nQuestion: " + q + "\n\n"
                      'Return STRICT JSON: {"terms": ["phrase", "phrase"]}'}]},
            timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = _json.loads(resp.json()["choices"][0]["message"]["content"])
        for t in (data.get("terms") or []):
            t = " ".join(str(t).strip().strip('"').split()[:5])
            if t and t.lower() not in [x.lower() for x in terms]:
                terms.append(t)
    except Exception:
        pass
    # heuristic fallback: capitalised/entity words as one phrase
    words = re.findall(r"[A-Za-z0-9']+", q)
    kept = [w for w in words if w[:1].isupper() or w.lower() not in _STOPWORDS]
    if kept:
        terms.append(" ".join(kept[:4]))
    return terms[:3] or [q]


def _search_term(question: str) -> str:
    """Single best discovery phrase (back-compat)."""
    terms = _search_terms(question)
    return terms[0] if terms else ""


# generic place / common words that must NOT qualify a feed as relevant on their own — they match
# unrelated regional shows (e.g. "Angeles" -> LA Rams/Kings fan podcasts). A real match needs a
# SPECIFIC shared token beyond these.
_WEAK_TOKENS = {"angeles", "national", "forest", "county", "city", "california", "state", "park",
                "valley", "north", "south", "east", "west", "university", "college", "daily",
                "show", "times", "news", "sports", "team", "fans", "united", "america", "american",
                "world", "york", "county", "coast", "river", "lake", "mount", "mountain", "river"}


def _sig_tokens(text: str) -> set:
    """Significant (topic-bearing) lowercase tokens: length >= 4, not question-scaffolding."""
    return {w.lower() for w in re.findall(r"[A-Za-z0-9']+", text or "")
            if len(w) >= 4 and w.lower() not in _STOPWORDS}


def _discover(question: str, *, max_feeds: int = 3) -> list:
    """Find RELEVANT feeds, not just any feeds. `byterm` matches feed titles literally, so we
    try candidate terms specific->general — but the old word-by-word back-off dropped to a single
    generic word ("Missing" -> matched "Ole Miss" / "Formula 1" junk). Fix (Noor's #1 lever): never
    back off below 2 meaningful words, AND relevance-filter every returned feed — keep it only if its
    title/description/author shares a topic-bearing token with the case. Junk with zero overlap is
    dropped, even if byterm returned it. Empty (honest no-op) beats junk."""
    terms = _search_terms(question)
    topic = _sig_tokens(question)   # the case's topic vocabulary
    for t in terms:
        topic |= _sig_tokens(t)
    seen, relevant = set(), []
    # candidate search terms: each distilled phrase, then trimmed to a 2-word floor (never 1 generic word)
    candidates = []
    for t in terms:
        w = t.split()
        candidates += [" ".join(w[:n]) for n in range(len(w), 1, -1)] or [t]
    for cand in dict.fromkeys(candidates):
        for f in search_feeds(cand, max_feeds=max_feeds * 3):
            url = f.get("url", "")
            if not url or url in seen:
                continue
            meta = _sig_tokens(f.get("title", "") + " " + f.get("desc", "") + " " + f.get("author", ""))
            if (topic & meta) - _WEAK_TOKENS:   # shares a SPECIFIC topic word (not just a place) -> relevant
                seen.add(url)
                relevant.append({"url": url, "title": f.get("title", "")})
                if len(relevant) >= max_feeds:
                    return relevant
    return relevant


def podcast_query(question: str, entities: list | None = None) -> dict:
    """Reframe an investigation into the PODCAST search engine's native mechanics (Gambit's insight):
    byterm matches SHOW TITLES / genre vocabulary, not case facts — so 'missing NASA scientists' finds
    junk, but 'true crime', 'conspiracy', 'unexplained', 'aerospace' find the shows that COVER it. This
    adapter knows it is in the podcast space and returns:
      - search_terms: podcast-native GENRE/topic phrases to find candidate shows (ordered focused->wide)
      - match_tokens: case-specific tokens (names, places, specifics) to then find the RIGHT EPISODE
        inside those shows.
    LLM first, heuristic fallback. Fail-open (never blocks the lane)."""
    q = (question or "").strip()
    out = {"search_terms": [], "match_tokens": set()}
    if not q:
        return out
    try:
        from .. import ratelimit
        import json as _json
        resp = ratelimit.post(
            "openrouter", _OPENROUTER_URL,
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.EXTRACTOR_MODEL,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "user", "content":
                      "You search PODCASTS (Podcast Index matches titles, descriptions, authors). Give "
                      "4-6 short (2-4 word) search phrases to find shows/episodes COVERING the case "
                      "below. Every phrase must be CASE-TIED — combine the case's subject matter with "
                      "a concrete noun from the case (e.g. 'NASA scientist death', 'Los Alamos "
                      "missing', 'scientist disappearance'). NO bare genre words ('true crime', "
                      "'conspiracy', 'unsolved mysteries' alone are useless — a query-quality audit "
                      "graded every such term C/F). Also give the case-specific MATCH TOKENS "
                      "(full names, place names, org names, unique terms) that identify the actual "
                      "episode about this case.\n\nCase: " + q + "\n\n"
                      'Return STRICT JSON: {"search_terms": ["NASA scientist death", "..."], '
                      '"match_tokens": ["Monica Reza", "Los Alamos", "..."]}'}]},
            timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = _json.loads(resp.json()["choices"][0]["message"]["content"])
        for t in (data.get("search_terms") or []):
            t = " ".join(str(t).strip().strip('"').split()[:3]).lower()
            if t and t not in out["search_terms"]:
                out["search_terms"].append(t)
        for m in (data.get("match_tokens") or []):
            m = str(m).strip().strip('"').lower()
            if len(m) >= 3:
                out["match_tokens"].add(m)
    except Exception:
        pass
    # fallback / augment match tokens: significant case tokens (names, orgs, places)
    if not out["match_tokens"]:
        out["match_tokens"] = {w for w in _sig_tokens(q) if w not in _WEAK_TOKENS}
    if not out["search_terms"]:
        out["search_terms"] = _search_terms(q)          # legacy title-based terms
    # NAME-FIRST SEARCH (Gambit, verified 2026-07-21): the genre-only premise was WRONG. Podcast Index
    # matches show DESCRIPTIONS and AUTHOR fields too, not just titles — so searching a PERSON'S NAME
    # surfaces the show dedicated to the case. Measured: 'Neil McCasland' / 'Monica Reza' /
    # 'Amy Eskridge' each return the show "Missing Scientists" (which names the whole roster in its
    # description), while genre terms ('true crime', 'government oversight') only ever found generic
    # shows. Names go FIRST (highest precision); genres stay as the wider net.
    names = [str(e).strip() for e in (entities or []) if str(e).strip()]
    if names:
        # FULL NAMES ONLY. A bare surname is far too generic and poisoned both the show search and the
        # episode match (measured 2026-07-21: 'Reza' -> 'Aprender ingles with Reza and Craig', 'The
        # Founder Mindset with Reza Satchu'; 'Eskridge' -> 'The Greta Eskridge Podcast' — and we then
        # WASTED Groq transcription on a German true-crime episode and a meditation episode). Full
        # names are precise: 'Neil McCasland'/'Monica Reza' each return the dedicated case show.
        name_terms = []
        for n in names[:12]:
            low = " ".join(n.lower().split())
            if len(low.split()) >= 2 and low not in name_terms:   # require first+last, never a lone token
                name_terms.append(low)
        out["search_terms"] = name_terms + [t for t in out["search_terms"] if t not in name_terms]
        # full names are also the strongest EPISODE match tokens (surnames alone false-match)
        for t in name_terms:
            out["match_tokens"].add(t)
    return out


def _discover_shows(search_terms: list, *, max_feeds: int) -> list:
    """Find candidate SHOWS via podcast-native genre terms. Relevance is deferred to the EPISODE level
    (transcribe_feed's match_tokens), so we do NOT drop a genre-right show here for lacking a case word
    in its title — that was exactly the bug. Dedup by feed url; cap the candidate pool."""
    seen, shows = set(), []
    for term in search_terms:
        for f in search_feeds(term, max_feeds=max_feeds * 2):
            url = f.get("url", "")
            if url and url not in seen:
                seen.add(url)
                shows.append({"url": url, "title": f.get("title", "")})
        if len(shows) >= max_feeds * 3:
            break
    return shows


def gather(question: str, *, num_results: int = 3, branch_id: str = "main",
           recency_years: int | None = None, entities: list | None = None) -> tuple:
    """Topic-driven podcast lane, ADAPTIVE (Gambit): reframe the question into podcast-native search
    terms (podcast_query) -> find candidate shows -> keep only episodes that mention the actual case
    (episode-level relevance) -> transcribe/extract. `entities` (a known roster) is the highest-value
    input: searching a PERSON'S NAME surfaces the show dedicated to the case, which genre terms never
    find. Start FOCUSED, WIDEN only if nothing hits. Harmless no-op with no keys."""
    plan = podcast_query(question, entities)
    terms, match_tokens = plan["search_terms"], plan["match_tokens"]
    if not terms:
        return [], []
    findings, transcripts = [], []
    # Adaptive waves. The focused wave must span BOTH the precise name terms (which find the show
    # dedicated to the case) AND a few genre terms (which find general true-crime/conspiracy shows
    # that cover it in one episode) — searching names alone found exactly ONE show and lost the
    # corroborating coverage (Vera: independent shows corroborate; Marcus: transcription stays capped
    # at max_eps per show, so the extra breadth is bounded).
    passes = [terms[:8], terms[8:]] if len(terms) > 8 else [terms]
    scanned = set()
    for wave in passes:
        if not wave:
            continue
        for show in _discover_shows(wave, max_feeds=num_results):
            if show["url"] in scanned:
                continue
            scanned.add(show["url"])
            fnd, tr = transcribe_feed(show["url"], question, max_eps=1, branch_id=branch_id,
                                      recency_years=recency_years, match_tokens=match_tokens)
            findings.extend(fnd)
            transcripts.extend(tr)
        if findings:                 # focused pass already yielded — don't widen (cost control)
            break
    return findings, transcripts
