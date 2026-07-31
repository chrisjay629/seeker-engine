"""Rate governor (brief 22) — one polite gate in front of every metered provider.

Seeker rents metered services (Exa, Jina, Firecrawl, OpenRouter, Groq, Perplexity, OpenAlex).
Bursting requests trips their per-window caps → 429s → runs collapse to YouTube-only (seen
repeatedly 2026-07-14). This module spreads and paces requests instead of slamming them:

  - per-provider CONCURRENCY cap (a semaphore) so we never fire more than N at once;
  - per-provider SPACING (a minimum interval between requests) so bursts get smoothed;
  - RETRY with exponential backoff + jitter on 429/5xx, honoring the server's `Retry-After`.

Fail-open (Vera): on exhausted retries it returns the LAST response, so the caller's existing
raise_for_status()/fallback path still fires — the governor can only help, never make things
worse. Wiring is explicit at each call site (Ghost: auditable, no monkeypatching).
"""
from __future__ import annotations

import os
import random
import threading
import time

import requests

from . import config

# Firecrawl is now the PRIMARY engine — web + primary + structured + youtube ALL route through it, so
# a cap of 2 (a free-tier leftover) starved lanes: they competed for 2 slots and one lost the race
# every run (v12: youtube 34->0 while the others hogged the budget). Hobby allows 5 concurrent; we run
# at 4 for headroom (a fetch burst shouldn't tip us over the server limit into 429s). Env-tunable so a
# plan change scales it without a code edit: SEEKER_FIRECRAWL_CONCURRENCY (Standard=50, Growth=100).
def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "")))
    except (ValueError, TypeError):
        return default

_FC_CONC = _int_env("SEEKER_FIRECRAWL_CONCURRENCY", 4)

# per-provider (max_concurrent, min_interval_seconds). Tuned conservative for the throttle-prone
# retrieval trio; looser for the LLM gateways which have higher ceilings.
_LIMITS = {
    "exa":        (3, 0.35),
    "jina":       (4, 0.20),
    "firecrawl":  (_FC_CONC, 0.30),
    "wayback":    (2, 0.40),
    "openrouter": (6, 0.10),
    "groq":       (6, 0.10),
    "perplexity": (3, 0.30),
    "openalex":   (4, 0.15),
    "default":    (4, 0.25),
}
_MAX_RETRIES = 4
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_BACKOFF = 30.0


class _Gate:
    """Concurrency cap + request spacing for one provider. Spacing is computed UNDER the lock,
    but the sleep happens OUTSIDE it (Noor: never sleep holding a lock)."""

    def __init__(self, n: int, interval: float):
        self.sem = threading.Semaphore(n)
        self.interval = interval
        self.lock = threading.Lock()
        self.next_ok = 0.0

    def __enter__(self):
        self.sem.acquire()
        with self.lock:
            target = max(time.monotonic(), self.next_ok)
            self.next_ok = target + self.interval
        wait = target - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        return self

    def __exit__(self, *exc):
        self.sem.release()
        return False


_gates: dict = {}
_gates_lock = threading.Lock()


def _gate(provider: str) -> _Gate:
    with _gates_lock:  # double-checked creation — one gate per provider, thread-safe
        g = _gates.get(provider)
        if g is None:
            n, interval = _LIMITS.get(provider, _LIMITS["default"])
            g = _Gate(n, interval)
            _gates[provider] = g
        return g


def request(provider: str, method: str, url: str, **kwargs) -> requests.Response:
    """Rate-governed HTTP request. Same signature/return as requests.request. Retries 429/5xx
    with backoff (honoring Retry-After); returns the last response once retries are exhausted so
    the caller's normal error handling runs (fail-open)."""
    # HANG GUARD (2026-07-19): a governed request holds the provider's concurrency semaphore for its
    # whole duration. If a caller forgot `timeout=`, a stalled socket waits FOREVER while holding that
    # slot — every other worker on the provider then blocks on acquire(), and the entire run deadlocks
    # (observed: a 6-hour freeze at step 0). Guarantee a finite timeout here so no governed call can
    # ever hang the run; a socket stall becomes a normal fail-open timeout instead of a deadlock.
    kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)
    last = None
    for attempt in range(_MAX_RETRIES + 1):
        with _gate(provider):
            resp = requests.request(method, url, **kwargs)
        if resp.status_code not in _RETRY_STATUS:
            return resp
        last = resp
        if attempt >= _MAX_RETRIES:
            break
        ra = resp.headers.get("Retry-After")
        if ra:
            try:
                # CAP the honored Retry-After (2026-07-19): a server (e.g. OpenAlex on its daily cap)
                # can send Retry-After: 600+ — honoring it verbatim slept ~10 min and the watchdog had
                # to abort the run. Never wait longer than _MAX_BACKOFF; if the server wants more, we
                # give up and fail open (return the last error) rather than freeze.
                delay = min(float(ra), _MAX_BACKOFF)
            except Exception:
                delay = min(2.0 ** attempt, _MAX_BACKOFF)
        else:
            delay = min(2.0 ** attempt, _MAX_BACKOFF)
        time.sleep(delay + random.uniform(0, 0.5))
    return last


def get(provider: str, url: str, **kwargs) -> requests.Response:
    return request(provider, "GET", url, **kwargs)


def post(provider: str, url: str, **kwargs) -> requests.Response:
    return request(provider, "POST", url, **kwargs)
