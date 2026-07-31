"""Source Credibility Ledger (owned by brief 06).

Persistent, updating credibility per domain. Scored up when a source proves
reliable (its content produced findings that corroborate the map), down when it
is caught contributing nothing or contradicting well-corroborated findings. The
Adversarial Agent reads it before every pre-flight. Compounds over time — the
system gets harder to fool the longer it runs. (Ghost: nothing trusted blindly.)
"""
from __future__ import annotations

import json

from ..config import REPO_ROOT

LEDGER_PATH = REPO_ROOT / "runs" / "credibility_ledger.json"
DEFAULT = 0.5
_STEP = 0.05
_MIN, _MAX = 0.05, 0.95


def _load() -> dict:
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save(d: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(d, indent=2))


def score(domain: str) -> float:
    return _load().get(domain, {}).get("score", DEFAULT)


def _bump(domain: str, delta: int, reason: str) -> float:
    d = _load()
    rec = d.get(domain, {"score": DEFAULT, "n": 0})
    rec["score"] = round(max(_MIN, min(_MAX, rec["score"] + delta * _STEP)), 3)
    rec["n"] = rec.get("n", 0) + 1
    rec["last"] = reason
    d[domain] = rec
    _save(d)
    return rec["score"]


def reward(domain: str, reason: str = "produced corroborated findings") -> float:
    return _bump(domain, +1, reason)


def penalize(domain: str, reason: str = "no usable findings") -> float:
    return _bump(domain, -1, reason)


def all_scores() -> dict:
    return {k: v.get("score") for k, v in _load().items()}


def lateral_read(domain: str, *, force: bool = False) -> str:
    """Lateral reading (Hunt upgrade H3 / SIFT-Investigate). Judge a source by what OTHER
    independent sources say about it — the fact-checker's move — NOT by the source's own
    claims. The Stanford finding: readers who left the site to check others judged credibility
    correctly; those who stayed on the page ("vertical reading") were fooled. So we search
    what others say, deliberately SKIP the source's own domain, and let a cheap model classify
    from that text only (no baked-in opinion — on-spine). Cached per domain; nudges the base
    score once. Returns 'credible' | 'mixed' | 'low' | 'unknown'."""
    d = _load()
    if d.get(domain, {}).get("lateral") and not force:
        return d[domain]["lateral"]
    from . import seeker_agent
    from .fetch import fetch
    from ..memory.gap_detector import _cheap_json
    import requests, re, html as _html

    def _direct_text(url):  # reputation pages fetch fine with a plain GET; proxies choke on them
        try:
            r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", r.text)
            h = re.sub(r"(?s)<[^>]+>", " ", h)
            return re.sub(r"\s+", " ", _html.unescape(h)).strip()
        except Exception:
            return None

    q = (f'What is the reputation, ownership, and credibility of the source "{domain}"? '
         'Is it considered reliable, biased, or unreliable by independent sources?')
    blob = ""
    try:
        for url, title in seeker_agent.exa_web_search(q, num_results=4):
            if domain in (url or ""):
                continue  # never judge a source by ITSELF (that's vertical reading)
            t = _direct_text(url) or fetch(url)
            if t:
                blob += f"\n[{title}]\n{t[:1500]}"
    except Exception:
        pass
    verdict = "unknown"
    if blob.strip():
        data = _cheap_json(
            f'Based ONLY on what these INDEPENDENT sources say about the source "{domain}", '
            "classify its credibility. Judge from the text below, NOT from your own prior "
            "knowledge. Return STRICT JSON "
            '{"verdict":"credible|mixed|low|unknown","why":"one line"}.\n\nSOURCES:' + blob)
        v = data.get("verdict", "unknown")
        if v in ("credible", "mixed", "low", "unknown"):
            verdict = v
    nudge = {"credible": +1, "low": -1}.get(verdict, 0)
    rec = d.get(domain, {"score": DEFAULT, "n": 0})
    if nudge:
        rec["score"] = round(max(_MIN, min(_MAX, rec["score"] + nudge * _STEP)), 3)
    rec["lateral"] = verdict
    d[domain] = rec
    _save(d)
    return verdict
