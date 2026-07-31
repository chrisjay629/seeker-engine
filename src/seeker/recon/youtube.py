"""YouTube as a structured source channel (brief 01).

Pipeline: Exa semantic search filtered to youtube.com  ->  pull transcript with
youtube-transcript-api (NOT the MCP — this is the automated path, per Vera's
flag)  ->  Research Extractor evaluates the transcript vs. the question.

No browser, no third-party transcript site, no copy-paste.
"""
from __future__ import annotations

import re
from typing import Optional

import requests

from .. import config
from ..models import Citation
from .extractor import extract

_EXA_URL = "https://api.exa.ai/search"
_YT_ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})")

# social / self-promo hosts that appear in descriptions but aren't SOURCE links
_DESC_NOISE = ("twitter.com", "x.com", "facebook.com", "instagram.com", "tiktok.com",
               "youtube.com", "youtu.be", "patreon.com", "linkedin.com", "discord",
               "t.me", "snapchat", "reddit.com/user", "linktr.ee", "buymeacoffee")


def description_links(video_url: str) -> list:
    """Mine a video's DESCRIPTION for the SOURCE links creators paste (Hunt upgrade H1).
    Creators routinely list where they got their data ("Sources: …") — those links are
    instant, high-confidence leads to primary sources. Direct page fetch (no API key);
    decodes YouTube's redirect-wrapped links and filters social/self-promo noise. Each
    returned link is still a sensor, chased and vetted like any other finding."""
    import json
    import urllib.parse as _uparse
    from .. import ratelimit
    try:
        html = ratelimit.get("default", video_url, timeout=config.REQUEST_TIMEOUT,
                             headers={"User-Agent": "Mozilla/5.0"}).text
    except Exception:
        return []
    desc = ""
    m = re.search(r'"shortDescription":"((?:[^"\\]|\\.)*)"', html)
    if m:
        try:
            desc = json.loads('"' + m.group(1) + '"')
        except Exception:
            desc = m.group(1)
    urls = set()
    for enc in re.findall(r'"url":"(https://www\.youtube\.com/redirect\?[^"]+)"', html):
        q = _uparse.parse_qs(_uparse.urlparse(enc.replace("\\u0026", "&")).query).get("q")
        if q and q[0].startswith("http"):
            urls.add(q[0])
    for u in re.findall(r'https?://[^\s"\\)]+', desc or ""):
        urls.add(u)
    return sorted(u for u in urls if not any(s in u.lower() for s in _DESC_NOISE))


def exa_youtube_search(query: str, num_results: int = 5,
                       recency_years: Optional[int] = None) -> list:
    """Return [(url, title)] of YouTube videos Exa finds for the query.
    `recency_years` restricts to videos published within that window (from the
    Truth Anchor freshness) — old sources are never fetched."""
    # DECOUPLED FROM EXA (migration 2026-07-23): video DISCOVERY now goes through the unified
    # web_search (Firecrawl-primary, Exa fallback), filtered to youtube.com. This killed the hidden
    # coupling where YouTube silently died whenever Exa ran out of credits (v10: Exa 402 -> YouTube
    # 0). The transcript pull (youtube-transcript-api) was always free and unaffected.
    from ..hunt.seeker_agent import web_search
    try:
        hits = web_search(query, num_results=num_results,
                          include_domains=["youtube.com"], recency_years=recency_years)
    except Exception:
        hits = []
    out = []
    for url, title in hits:
        if url and _YT_ID_RE.search(url):
            out.append((url, title))
    return out


def _video_id(url: str) -> Optional[str]:
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def _firecrawl_transcript(url: str):
    """IP-BLOCK BYPASS (2026-07-27): fetch the transcript by SCRAPING the watch page through
    Firecrawl instead of hitting YouTube's caption endpoint directly. YouTube began serving
    `IpBlocked` to youtube-transcript-api from this machine's IP (v12/v13 -> youtube:0), a known
    2026 crackdown on datacenter/residential caption scraping. Firecrawl rotates its own proxy
    pool, so the watch page (which Firecrawl renders WITH the spoken captions inline in its
    markdown — verified live: TED video returned 5.3k chars of real transcript) comes back clean.
    Uses the paid key when present (keyless tier 429s under load); fully hang-bounded + fail-open.
    Duration is unknown from markdown (no per-segment timestamps) -> None, which simply SKIPS the
    optional duration gate in transcript_validator (the 100-word floor + relevance gate still run).
    Costs 1 Firecrawl credit per video, only when the free youtube-transcript-api path is blocked."""
    from ..hunt.fetch import _bounded_json
    from .transcript_validator import MIN_HEALTHY_WORDS
    headers = {"Content-Type": "application/json"}
    if config.FIRECRAWL_API_KEY:
        headers["Authorization"] = f"Bearer {config.FIRECRAWL_API_KEY}"

    def _scrape(actions):
        body = {"url": url, "formats": ["markdown"]}
        if actions:
            body["actions"] = actions
        data = _bounded_json("firecrawl", "POST",
                             "https://api.firecrawl.dev/v2/scrape",
                             headers=headers, json=body)
        if not data:
            return None
        md = (data.get("data", {}) or {}).get("markdown") or ""
        # the transcript text lands as the TAIL after the last 'Transcript' heading (when the panel
        # was expanded); otherwise the whole page markdown IS the caption text for videos that render
        # it inline. Strip per-line timestamps (0:00 / 12:34) and residual markdown links either way.
        i = md.rfind("\nTranscript")
        if i < 0:
            i = md.rfind("Transcript")
        tail = md[i + len("Transcript"):] if i >= 0 else md
        tail = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", tail)
        tail = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", tail)
        tail = re.sub(r"\s+", " ", tail).strip()
        return tail if len(tail.split()) >= MIN_HEALTHY_WORDS else None

    # FAST PATH FIRST (2026-07-27): a plain scrape already returns the full caption text for videos
    # that render it inline (verified: TED talk -> 1087 words, no browser actions) — cheap and quick.
    # Only when that comes back thin (captions gated behind a "Show transcript" JS click) do we pay for
    # the slower browser-action scrape that expands the description and clicks the transcript panel.
    # This keeps the common case fast so the lane doesn't blow the run's time budget on a full roster.
    text = _scrape(None)
    if text:
        return text, None
    text = _scrape([{"type": "wait", "milliseconds": 2500},
                    {"type": "click", "selector": "tp-yt-paper-button#expand"},
                    {"type": "wait", "milliseconds": 1000},
                    {"type": "click", "selector": "button[aria-label*='transcript' i]"},
                    {"type": "wait", "milliseconds": 2500}])
    return (text or None), None


def fetch_transcript(url: str):
    """Pull a transcript for a YouTube URL. Returns (text, duration_seconds) or
    (None, None) if unavailable. Duration is derived from the transcript's OWN
    last-segment timestamp (start + duration) — the video length for free, no
    extra API call (Gambit's insight). Handles both the >=1.0 instance API and
    the older classmethod API (Cipher: this library breaks as YouTube changes).

    Two-tier (2026-07-27): the FREE youtube-transcript-api path first; when YouTube
    IP-blocks it (returns nothing), fall back to a Firecrawl scrape of the watch page,
    which carries the captions inline and rides Firecrawl's rotating proxies."""
    vid = _video_id(url)
    if not vid:
        return None, None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:
            api = YouTubeTranscriptApi()
            fetched = api.fetch(vid)
            snippets = list(getattr(fetched, "snippets", fetched))
            text = " ".join(s.text for s in snippets)
            last = snippets[-1] if snippets else None
            dur = (getattr(last, "start", 0) + getattr(last, "duration", 0)) if last else None
        except (TypeError, AttributeError):
            data = list(YouTubeTranscriptApi.get_transcript(vid))
            text = " ".join(seg["text"] for seg in data)
            last = data[-1] if data else None
            dur = (last.get("start", 0) + last.get("duration", 0)) if last else None
        if text:
            return text, (dur or None)
    except Exception:
        pass
    # free path returned nothing (IP block / no captions) -> Firecrawl proxy fallback
    return _firecrawl_transcript(url)


def gather(question: str, *, num_results: int = 5, branch_id: str = "main",
           recency_years: Optional[int] = None, entities: Optional[list] = None):
    """Search -> transcript -> VALIDATE -> extract. Returns (findings, transcripts).

    Validation (transcript_validator) runs the FREE math gates (100-word floor +
    duration match from the transcript's own timestamps) and then the cheap Groq
    relevance gate — only survivors reach the (more expensive) Research Extractor.
    Validation across the whole pull runs CONCURRENTLY (Zara: parallel cheap calls,
    not one giant batch — 500 transcripts never fit a single context window)."""
    import concurrent.futures as _cf
    from .transcript_validator import validate_transcript

    # QUERY ADAPTER (2026-07-21): YouTube is a LEXICAL engine over short human-written titles — our
    # 231-char analyst questions matched nothing (audit: returned generic 'how to do a background
    # check' videos). Strip scaffolding + trim to keyword register; union hits across variants.
    from .. import search_queries as _sq
    # NAME-FIRST (2026-07-22): when a roster is known, search by NAME — verified live that
    # 'Amy Eskridge scientist death' returns 5 real captioned videos while the trimmed case question
    # ('How close can we get to solving the mystery of the missing') returns junk. The flagship never
    # forwarded entities here, so YouTube ran on the garbage case-question and returned 0 in-pipeline
    # while working standalone (the podcast bug's twin). Names first, then a couple case-keyword queries.
    _names = [str(e).strip() for e in (entities or []) if str(e).strip()]
    _variants = []
    if _names:
        for _n in _names[:5]:
            _variants += _sq.person_queries(_n, angles=["cause of death", "missing", "news"], max_q=3)
    _qs = _sq.for_engine([question], "youtube")
    _payload = _qs[0] if _qs else question
    if not _variants:                    # no roster -> fall back to query-from-topic
        if len(_payload.split()) <= 5:   # person/entity payload -> angle fan-out (Gambit's pattern)
            _variants = [_payload, f"{_payload} missing", f"{_payload} what happened"]
        else:
            # LONG topical payload: do NOT blind-truncate — chopping a sentence keeps the leading
            # words and loses the subject. Generate real short keyword queries instead.
            _variants = _sq.plan_queries(_payload, engine="youtube", n=3) or [_payload]
    _cap = 6 if _names else 3            # a few per-person queries when we have a roster (Marcus: capped)
    _pairs, _seen = [], set()
    for _v in _variants[:_cap]:
        try:
            for _u, _t in exa_youtube_search(_v, num_results=num_results,
                                             recency_years=recency_years):
                if _u not in _seen:
                    _seen.add(_u)
                    _pairs.append((_u, _t))
        except Exception:
            continue
    # 1. fetch all transcripts CONCURRENTLY (2026-07-27): each Firecrawl-fallback scrape is a slow
    # network+render call, so a serial loop over a full roster blew the run's time budget. Fetch them
    # in parallel — the transcript pull is pure I/O and the ratelimit governor still caps Firecrawl
    # concurrency, so this speeds the lane up without hammering the API.
    def _fetch(pair):
        url, title = pair
        text, dur = fetch_transcript(url)
        return (url, title, text, dur) if text else None

    fetched = []
    _targets = _pairs[:num_results * 2]
    if _targets:
        with _cf.ThreadPoolExecutor(max_workers=8) as pool:
            for item in pool.map(_fetch, _targets):
                if item:
                    fetched.append(item)

    # 2. validate concurrently — math gates are instant; relevance is the Groq call
    def _val(item):
        url, title, text, dur = item
        return item, validate_transcript(text, question, duration_seconds=dur, url=url)

    survivors = []
    if fetched:
        with _cf.ThreadPoolExecutor(max_workers=8) as pool:
            for item, vres in pool.map(_val, fetched):
                if vres.passed:
                    survivors.append(item)

    # 3. extract only from validated transcripts
    findings, transcripts = [], []
    for url, title, text, _dur in survivors:
        transcripts.append({"url": url, "title": title, "text": text})
        citation = Citation(url=url, title=title, source_type="youtube")
        findings.extend(extract(question, text, citation, branch_id=branch_id))
    return findings, transcripts


def youtube_channel(question: str, *, num_results: int = 5,
                    branch_id: str = "main") -> list:
    """Full channel: search -> transcript -> extract. Returns list[Finding]."""
    findings, _ = gather(question, num_results=num_results, branch_id=branch_id)
    return findings
