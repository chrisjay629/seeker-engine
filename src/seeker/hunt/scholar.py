"""OpenAlex scholarly-graph client — the legal, free backbone for citation chaining.

Instead of scraping article HTML and slamming into paywalls, Seeker rides the OpenAlex
graph (free, no API key; we join the 'polite pool' with a mailto). For any paper it gives:
  - referenced_works — its OWN reference list as SPECIFIC papers (not journal names), so
    citation-chaining finally has precise, chase-able targets;
  - cited_by — papers that cite it LATER (has this been confirmed or overturned since?);
  - open_access.oa_url — a link to the LEGAL free copy when one exists;
  - an abstract even for closed papers (reconstructed from the inverted index).

We NEVER bypass a paywall (Ghost). When a paper is closed AND has no open copy, we return
no text — the caller records a 'gated lead' marker and goes looking for secondary coverage
(reviews/summaries) elsewhere. An abstract or a review is a sensor, vetted like any finding.
"""
from __future__ import annotations

import re
from typing import Optional

import requests

from .. import config

_API = "https://api.openalex.org"
_MAILTO = "chrisjay629@gmail.com"           # polite-pool identifier (public contact, not a secret)
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'&?#]+", re.I)


def _get(path: str, **params) -> Optional[dict]:
    """One polite GET against OpenAlex. Fail-open: returns None on any error."""
    params["mailto"] = _MAILTO
    try:
        from .. import ratelimit
        r = ratelimit.get("openalex", f"{_API}/{path}", params=params,
                          timeout=config.REQUEST_TIMEOUT,
                          headers={"User-Agent": f"Seeker/1.0 (mailto:{_MAILTO})"})
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def doi_from(text: str) -> str:
    """Pull a bare DOI out of a URL or citation string ('' if none)."""
    m = _DOI_RE.search(text or "")
    return m.group(0).rstrip(".").lower() if m else ""


def resolve(url_or_title: str) -> Optional[dict]:
    """Find the OpenAlex work for a link, DOI, or title. DOI first (exact), then a title
    search (best-effort). Returns the work dict or None."""
    doi = doi_from(url_or_title)
    if doi:
        w = _get(f"works/https://doi.org/{doi}")
        if w and not w.get("error"):
            return w
    # no DOI (or DOI miss) — treat the string as a title and search
    title = (url_or_title or "").strip()
    if len(title) >= 12 and not title.lower().startswith("http"):
        res = _get("works", filter=f"title.search:{title}", per_page=1)
        results = (res or {}).get("results", [])
        return results[0] if results else None
    return None


# NOTE (2026-07-18): author-seeding (works_by_person via OpenAlex author search) was TESTED and
# REJECTED — it false-attributes: 'Steven Garcia' -> von Neumann's game-theory book, 'Nuno Loureiro'
# (MIT physicist) -> a different Loureiro's biology paper. A bare name cannot be disambiguated to a
# specific author, so seeding the citation-graph by person names attributes papers to the wrong real
# people — the exact harm we fight. Do NOT re-add without reliable author-ID disambiguation.


def reconstruct_abstract(work: dict) -> str:
    """Rebuild the abstract text from OpenAlex's inverted index ('' if none)."""
    inv = (work or {}).get("abstract_inverted_index") or {}
    if not inv:
        return ""
    positions = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def primary_url(work: dict) -> str:
    """The best human URL for a work: its DOI, else the landing page, else the OpenAlex id."""
    if not work:
        return ""
    if work.get("doi"):
        return work["doi"]
    loc = (work.get("primary_location") or {})
    return loc.get("landing_page_url") or work.get("id", "")


def referenced_ids(work: dict, limit: int = 25) -> list:
    """The OpenAlex ids of the work's OWN references (its citation list)."""
    return (work or {}).get("referenced_works", [])[:limit]


def fetch_works(ids: list, per_page: int = 25) -> list:
    """Batch-fetch works by OpenAlex id (one call). Ids may be full URLs or bare Wxxxx."""
    if not ids:
        return []
    short = "|".join(i.split("/")[-1] for i in ids[:per_page])
    res = _get("works", filter=f"openalex_id:{short}", per_page=per_page)
    return (res or {}).get("results", [])


def cited_by(work: dict, per_page: int = 10, recency_years: int | None = None) -> list:
    """Papers that cite this work LATER — forward chaining (confirmed/overturned since?).
    Optionally restricted to the last `recency_years`."""
    wid = (work or {}).get("id", "")
    if not wid:
        return []
    flt = f"cites:{wid.split('/')[-1]}"
    if recency_years:
        from ..recon.recency import start_date
        sd = start_date(recency_years)
        if sd:
            flt += f",from_publication_date:{sd[:10]}"
    res = _get("works", filter=flt, per_page=per_page, sort="cited_by_count:desc")
    return (res or {}).get("results", [])


def readable_text(work: dict) -> tuple:
    """Best LEGAL text for a work. Returns (text, url, kind):
      kind='oa_fulltext' — fetched the open-access copy;
      kind='abstract'    — no open copy, but OpenAlex has the abstract;
      kind='gated'       — closed and no abstract: text is '' (caller records the lead).
    Never bypasses access controls (Ghost)."""
    from .fetch import fetch
    url = primary_url(work)
    oa = (work or {}).get("open_access", {}) or {}
    oa_url = oa.get("oa_url")
    if oa_url:
        try:
            text = fetch(oa_url)
        except Exception:
            text = None
        if text:
            return text, oa_url, "oa_fulltext"
    ab = reconstruct_abstract(work)
    if ab:
        return ab, url, "abstract"
    return "", url, "gated"
