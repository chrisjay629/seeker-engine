"""Fetch layer (owned by brief 06; imported by Recon Pass).

Two-tier, cost-disciplined: Jina Reader first (cheap, trims to clean text),
Firecrawl only as the fallback for JS-rendered / anti-bot pages Jina can't reach.
Skimming is nearly free; comprehension is the meter — so fetch is dumb and cheap.
"""
from __future__ import annotations

import json as _json
import time as _time
from urllib.parse import urlparse
from typing import Optional

import requests

from .. import config
from .. import ratelimit

# HARD fetch bounds (2026-07-19). requests' `timeout` only fires on DEAD AIR (no bytes for N sec) — a
# server that dribbles a chunked body slowly, or streams an endless one, never trips it and reads
# FOREVER (this is what hung the run for 6h, caught by the watchdog). So we stream the body and enforce
# a wall-clock DEADLINE and a byte CAP: a fetch now always terminates. read-timeout catches dead air,
# the deadline catches the slow-trickle/endless case.
_MAX_FETCH_BYTES = 6_000_000          # 6 MB is plenty of clean page text; beyond it is never worth it
_FETCH_DEADLINE = 75                   # hard wall-clock ceiling for reading one body
_STREAM_TIMEOUT = (10, 30)             # (connect, read-gap) — dead air aborts in 30s


def _bounded_json(provider: str, method: str, url: str, **kwargs) -> Optional[dict]:
    """Rate-governed request whose body is read under a HARD wall-clock deadline + byte cap, then
    parsed as JSON. Streams so the concurrency slot is freed after headers, not held through the read.
    Returns None on any error/timeout (fail-open) — a slow page is skipped, never a hang."""
    kwargs["stream"] = True
    kwargs["timeout"] = _STREAM_TIMEOUT
    resp = None
    try:
        # the request itself can raise (connect/read timeout, DNS, reset) — it MUST be inside the try
        # or a slow page crashes the whole run instead of failing open (regression fixed 2026-07-19).
        resp = ratelimit.request(provider, method, url, **kwargs)
        resp.raise_for_status()
        start, total, chunks = _time.monotonic(), 0, []
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
            if total > _MAX_FETCH_BYTES or (_time.monotonic() - start) > _FETCH_DEADLINE:
                break                  # trickle / oversized / endless stream — stop hard
        return _json.loads(b"".join(chunks).decode("utf-8", "replace"))
    except Exception:
        return None
    finally:
        if resp is not None:
            resp.close()


def _bounded_text(provider: str, method: str, url: str, **kwargs) -> Optional[str]:
    """Same hard-bounded streamed read as _bounded_json, but returns raw text (for HTML pages, e.g. the
    Wayback raw snapshot). None on error/timeout — a slow page is skipped, never a hang."""
    kwargs["stream"] = True
    kwargs["timeout"] = _STREAM_TIMEOUT
    resp = None
    try:
        resp = ratelimit.request(provider, method, url, **kwargs)
        resp.raise_for_status()
        start, total, chunks = _time.monotonic(), 0, []
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                chunks.append(chunk)
                total += len(chunk)
            if total > _MAX_FETCH_BYTES or (_time.monotonic() - start) > _FETCH_DEADLINE:
                break
        return b"".join(chunks).decode("utf-8", "replace")
    except Exception:
        return None
    finally:
        if resp is not None:
            resp.close()


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def jina_fetch(url: str) -> Optional[str]:
    data = _bounded_json(
        "jina", "GET", f"https://r.jina.ai/{url}",
        headers={"Authorization": f"Bearer {config.JINA_API_KEY}",
                 "Accept": "application/json"})
    if not data:
        return None
    return (data.get("data", {}) or {}).get("content") or None


def firecrawl_fetch(url: str) -> Optional[str]:
    # KEYLESS (2026-07-22): no Authorization header -> Firecrawl's free keyless /scrape tier
    # (verified live, HTTP 200). Revives the deep-fetch fallback, which had gone silently dead when
    # the paid key ran out of credits (402), at zero cost. Fail-open like always.
    data = _bounded_json(
        "firecrawl", "POST", "https://api.firecrawl.dev/v2/scrape",
        headers={"Content-Type": "application/json"},
        json={"url": url, "formats": ["markdown"]})
    if not data:
        return None
    return (data.get("data", {}) or {}).get("markdown") or None


def firecrawl_dynamic_fetch(url: str) -> Optional[str]:
    """Firecrawl with browser ACTIONS (verified /v2/scrape `actions` schema) — scroll to trigger
    lazy-load / infinite-scroll and wait for render, then scrape. Reaches JS-heavy, paginated, and
    infinite-scroll pages a one-shot scrape returns thin on (e.g. forum sleuth threads). Fail-open:
    None on any error so the caller's next tier still runs. Same key/quota as firecrawl_fetch."""
    data = _bounded_json(
        "firecrawl", "POST", "https://api.firecrawl.dev/v2/scrape",
        headers={"Content-Type": "application/json"},   # keyless — no Authorization on purpose
        json={"url": url, "formats": ["markdown"],
              "actions": [{"type": "wait", "milliseconds": 1200},
                          {"type": "scroll", "direction": "down"},
                          {"type": "wait", "milliseconds": 1000},
                          {"type": "scroll", "direction": "down"},
                          {"type": "wait", "milliseconds": 1000}]})
    if not data:
        return None
    return (data.get("data", {}) or {}).get("markdown") or None


def wayback_fetch(url: str) -> Optional[str]:
    """Last resort: recover a dead/blocked page from the Internet Archive's Wayback
    Machine (Hunt upgrade H2). Finds the closest archived snapshot and reads it. The
    snapshot's web.archive.org URL is what gets cited downstream, so provenance stays
    honest — it's a historical snapshot, not the live page (Vera)."""
    import re
    import html as _html
    try:
        r = ratelimit.get("wayback", "http://archive.org/wayback/available",
                          params={"url": url}, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        snap = ((r.json().get("archived_snapshots") or {}).get("closest") or {})
        snap_url = snap.get("url") if snap.get("available") else None
        if not snap_url:
            return None
        # Jina/Firecrawl proxies reject web.archive.org, but a DIRECT GET works. Use the
        # `id_` raw variant (original page bytes, no archive toolbar) and strip the HTML.
        raw_url = re.sub(r"(/web/\d+)/", r"\1id_/", snap_url, count=1)
        body = _bounded_text("wayback", "GET", raw_url, headers={"User-Agent": "Mozilla/5.0"})
        if not body:
            return None
        h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", body)
        h = re.sub(r"(?s)<[^>]+>", " ", h)
        text = re.sub(r"\s+", " ", _html.unescape(h)).strip()
        return text if len(text) >= 200 else None
    except Exception:
        return None


def fetch(url: str, *, min_chars: int = 200) -> Optional[str]:
    """Deep-read a page: Jina first, Firecrawl fallback, then the Internet Archive if the
    live page is dead/blocked. None if all fail."""
    from .. import watchdog
    watchdog.beat("fetching")   # each page fetch is progress — resets the stall clock
    text = jina_fetch(url)
    if text and len(text) >= min_chars:
        return text
    text = firecrawl_fetch(url)
    if text and len(text) >= min_chars:
        return text
    # dynamic-page escalation: only when the one-shot scrape came back thin (JS/lazy/infinite-scroll)
    text = firecrawl_dynamic_fetch(url)
    if text and len(text) >= min_chars:
        return text
    return wayback_fetch(url)  # dead/blocked live page -> recover from the archive
