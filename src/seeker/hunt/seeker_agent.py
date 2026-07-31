"""The Seeker — precision hunter (brief 06).

Never hunts blind: receives a question that survived the Adversarial pre-flight,
aimed at a specific gap. Skims cheap (Exa highlights), deep-reads only survivors
(Jina -> Firecrawl), returns learning + citation via the Research Extractor.
Never hauls raw data home — only findings and citations.
"""
from __future__ import annotations

import requests

from .. import config
from ..models import Citation
from ..recon.extractor import extract
from . import fetch as fetchlib

_EXA_URL = "https://api.exa.ai/search"

# Run-scoped case anchor (distinctive case terms) — set ONCE per investigation by the director so the
# structured/registry lane can turn a bare person name into a gov-searchable topic query, without
# threading the anchor through _drive_leads -> _drive_lead -> hunt -> seek_structured (5 signatures).
# Seeker runs one investigation per process, so a module-level value is safe here (single-run scope).
_CASE_ANCHOR = ""
_ID_CARDS = {}          # {name: identity card} — per-person namesake anchors (task #41)


def set_identity_cards(cards: dict) -> None:
    """Run-scoped identity cards, so the SEARCH LANES can anchor a bare name to the right person.

    These lanes were the actual namesake leak: person_queries has taken a disambiguating `context`
    since v11, and of its four callers only the director's equalizer ever passed one — the two web
    lanes and YouTube, which do the bulk of the searching, all went out on the bare name. The case
    anchor helped only in the structured lane. A card beats the anchor anyway: 'missing scientists'
    is shared by the whole roster and separates no one from their own namesake."""
    global _ID_CARDS
    _ID_CARDS = dict(cards or {})


def _anchor_for(payload: str) -> str:
    """The tightest anchor available for this payload: the person's own card, else the case anchor."""
    try:
        from .. import identity as _id
        key = " ".join(str(payload or "").split()).lower()
        for name, card in _ID_CARDS.items():
            if name.lower() == key or (len(key) > 3 and key in name.lower()):
                return _id.disambiguator(card) or _CASE_ANCHOR
    except Exception:
        pass
    return _CASE_ANCHOR


def set_case_anchor(anchor: str) -> None:
    """Director sets the run's case anchor once (distinctive subject terms). Fail-safe to ''."""
    global _CASE_ANCHOR
    _CASE_ANCHOR = " ".join((anchor or "").split())


def exa_web_search(query: str, num_results: int = 6,
                   include_domains: list | None = None,
                   recency_years: int | None = None) -> list:
    """Skim: Exa semantic search over the open web. Returns [(url, title)].
    `include_domains` restricts to curated authoritative sources.
    `recency_years` restricts to sources published within that window."""
    from ..recon.recency import start_date
    body = {"query": query, "type": "auto", "numResults": num_results,
            "contents": {"highlights": True}}
    if include_domains:
        body["includeDomains"] = include_domains
    sd = start_date(recency_years)
    if sd:
        body["startPublishedDate"] = sd
    from .. import ratelimit
    r = ratelimit.post(
        "exa", _EXA_URL,
        headers={"x-api-key": config.EXA_API_KEY, "Content-Type": "application/json"},
        json=body, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    return [(res.get("url", ""), res.get("title", ""))
            for res in r.json().get("results", []) if res.get("url")]


_FC_SEARCH_URL = "https://api.firecrawl.dev/v2/search"


def firecrawl_search(query: str, num_results: int = 6,
                     recency_years: int | None = None,
                     categories: list | None = None,
                     include_domains: list | None = None) -> list:
    """Firecrawl /search with its trained relevance model — returns the EXCERPTS that answer the
    query (94.7% SimpleQA, ~10x fewer tokens than full pages), not just links.

    AUTH (2026-07-23): prefer the KEYED tier when FIRECRAWL_API_KEY is set (Hobby+ = 5,000 credits/
    mo, higher rate limits) — that's the funded path once subscribed. On a keyed 402/429 (out of
    credits / throttled) OR when no key is set, retry KEYLESS (no Authorization header — Firecrawl's
    free IP-metered tier). So the same code runs free today and uses the paid quota the instant a
    key with credits exists, with keyless as the always-there floor. Fail-open upstream.

    The relevance-model excerpt comes back in each row's `description` (keyless) or `highlights`
    (keyed scrapeOptions). `categories=['research']` taps the arXiv Research Index;
    `include_domains` restricts to a curated set (used by the structured-registry lane)."""
    from .. import ratelimit

    def _call(keyed: bool):
        body = {"query": query, "limit": num_results}
        if categories:
            body["categories"] = categories
        if include_domains:
            body["includeDomains"] = include_domains
        if recency_years:   # tbs: coarsest-that-fits ('past year' is the finest year-scale bucket)
            body["tbs"] = "qdr:y"
        headers = {"Content-Type": "application/json"}
        if keyed:
            headers["Authorization"] = f"Bearer {config.FIRECRAWL_API_KEY}"
        return ratelimit.post("firecrawl", _FC_SEARCH_URL, headers=headers,
                              json=body, timeout=config.REQUEST_TIMEOUT)

    r = None
    if config.FIRECRAWL_API_KEY:
        try:
            r = _call(keyed=True)
            if r.status_code in (401, 402, 429):   # no credits / bad key / throttled -> try keyless
                r = None
        except Exception:
            r = None
    if r is None:
        r = _call(keyed=False)                      # keyless: no key, or keyed unavailable
    r.raise_for_status()
    data = r.json().get("data", {})
    rows = data.get("web", []) if isinstance(data, dict) else (data or [])
    out = []
    for res in rows:
        url = res.get("url", "")
        if not url:
            continue
        # keyless returns the relevance-model excerpt in `description`; `highlights` appears only
        # with paid scrapeOptions — support both so a future keyed upgrade needs no code change.
        hl = res.get("highlights") or []
        excerpt = " ".join(h if isinstance(h, str) else str(h.get("text", "")) for h in hl).strip()
        if not excerpt:
            excerpt = (res.get("description") or "").strip()
        out.append((url, res.get("title", ""), excerpt[:4000]))
    return out


def web_search(query: str, num_results: int = 6,
               include_domains: list | None = None,
               recency_years: int | None = None) -> list:
    """UNIFIED search entry (migration 2026-07-23) — the ONE search call the web / primary /
    structured lanes share. Firecrawl-primary, Exa optional-fallback.

    Why: v10 proved both engines were single-tier and failed together (Exa 402, Firecrawl keyless
    429). Firecrawl /search covers everything these lanes actually use — query, includeDomains, a
    (coarser) recency filter — so it becomes primary; Exa stays as a fallback only, so a Firecrawl
    outage still degrades gracefully instead of going dark. Engine order is env-tunable
    (SEEKER_SEARCH_PRIMARY = 'firecrawl' | 'exa'). Returns [(url, title)] — the excerpt is dropped
    here because these lanes deep-read the full page anyway (the excerpt-first optimization lives in
    the dedicated Firecrawl lane). Fail-open to [] so one dead engine never crashes a hunt."""
    import os
    primary = os.environ.get("SEEKER_SEARCH_PRIMARY", "firecrawl").strip().lower()

    def _fc():
        return [(u, t) for (u, t, _ex) in firecrawl_search(
            query, num_results=num_results, recency_years=recency_years,
            include_domains=include_domains)]

    def _exa():
        return exa_web_search(query, num_results=num_results,
                              include_domains=include_domains, recency_years=recency_years)

    order = [_fc, _exa] if primary != "exa" else [_exa, _fc]
    for _engine in order:
        try:
            hits = _engine()
            if hits:
                return hits
        except Exception:
            continue
    return []


def _looks_scientific(question: str) -> bool:
    """Cheap gate for tapping the Firecrawl Research Index (arXiv+repos) on science-flavored leads."""
    ql = (question or "").lower()
    return any(w in ql for w in ("research", "scientist", "paper", "study", "physics", "patent",
                                 "engineer", "laboratory", "professor", "phd", "arxiv"))


def seek_firecrawl(question: str, *, branch_id: str = "main", max_pages: int = 4,
                   recency_years: int | None = None) -> list:
    """The Firecrawl search lane. Extraction runs DIRECTLY on the returned excerpts (they're the
    query-relevant paragraphs — verbatim, citable, no fetch round-trip); a page is deep-read only
    when no excerpt came back. Findings tagged source_type 'web' like the Exa lane; dedup against
    Exa's hits happens downstream in consolidation. Fail-open to []."""
    from .. import search_queries as _sq
    _qs = _sq.for_engine([question], "web")
    _payload = _qs[0] if _qs else question
    if len(_payload.split()) <= 5:      # short person/org payload -> angle fan-out, same as seek()
        _variants = _sq.person_queries(_payload, context=_anchor_for(_payload), max_q=3)
    else:
        _variants = [_payload]
    # Search plans: ALWAYS the plain web search (it returns the news/record excerpts that answer
    # status/cause questions). For science-flavored leads ADD one research-index pass as a BONUS —
    # never a replacement (verified 2026-07-22: research-only surfaced the victim's CV/citation
    # pages, not her death; extract correctly found 0. Union keeps both — Noor's either/or catch).
    plans = [(v, None) for v in _variants[:3]]
    if _looks_scientific(question):
        plans.append((_variants[0], ["research"]))
    hits, seen = [], set()
    for _v, _cats in plans:
        try:
            for u, t, ex in firecrawl_search(_v, num_results=max_pages + 2,
                                             recency_years=recency_years, categories=_cats):
                if u not in seen:
                    seen.add(u)
                    hits.append((u, t, ex))
        except Exception:
            continue
    findings = []
    for url, title, excerpt in hits:
        if len(findings) >= max_pages * 3:
            break
        text = excerpt or fetchlib.fetch(url)     # excerpt-first: the 10x token saving
        if not text:
            continue
        # tagged DISTINCTLY from the Exa lane ('web') so the organ mix shows what each engine
        # actually contributed — v9 lumped both into web:769 and couldn't answer "do we need Exa?"
        cit = Citation(url=url, title=title, source_type="web_firecrawl")
        findings.extend(extract(question, text, cit, branch_id=branch_id))
    return findings


# PRIMARY-source signals — a URL touching one of these is likely the origin document
# (peer-reviewed paper, filing, dataset, official record), not commentary about it.
_PRIMARY_HINTS = ("doi.org", "pubmed", "ncbi.nlm.nih.gov", "nature.com", "sciencedirect",
                  "springer", "onlinelibrary.wiley", "nejm.org", "thelancet", "bmj.com",
                  "jamanetwork", "academic.oup.com", "arxiv.org", "ssrn.com", "sec.gov",
                  "clinicaltrials.gov", "data.gov", "who.int", "cdc.gov", "nih.gov",
                  ".edu/", "researchgate.net", "cochranelibrary")


def is_primary_source(url: str) -> bool:
    """True if a URL looks like a PRIMARY source (the origin document) vs. commentary."""
    return any(h in (url or "").lower() for h in _PRIMARY_HINTS)


def seek_primary(question: str, *, branch_id: str = "main", max_pages: int = 4,
                 recency_years: int | None = None) -> list:
    """Primary-source-preferring hunt (Hunt upgrade H4). A master researcher goes to the
    ORIGIN — the paper, the filing, the dataset — not a blog summarizing it. Two levers:
    (1) augment the query toward primary documents, (2) rerank Exa hits so primary-looking
    domains are fetched first. Findings from a primary get citation source_type
    "primary_source" so triangulation/synthesis can weight them. Still vetted like any
    finding — 'primary' is a provenance tag, not a truth stamp (Vera)."""
    # QUERY ADAPTER (2026-07-21, audit fix): the blanket academic suffix was BROKEN for person-status
    # leads — '(peer-reviewed study, original paper...)' on 'Verify ... : Amy Eskridge' told Exa to
    # find papers ABOUT a missing person, returning the victims' own publications (their CVs), which
    # downstream could misread as status info. For a PERSON payload the primary sources are police/
    # coroner/official records — aim there. The academic suffix stays for research-claim leads only.
    from .. import search_queries as _sq
    _stripped = _sq.strip_instructions(question)
    if len(_stripped.split()) <= 5:      # short entity payload -> a person/org, not a research claim
        aug = f"{_stripped} police report coroner official statement news"
    else:
        aug = (f"{_stripped} (peer-reviewed study, original paper, dataset, official filing, "
               "or primary source)")
    try:
        hits = web_search(aug, num_results=max_pages + 4, recency_years=recency_years)  # Firecrawl-primary
    except Exception:
        return []
    # primary-looking domains first; keep the rest as fallback
    hits.sort(key=lambda ut: 0 if is_primary_source(ut[0]) else 1)
    findings = []
    for url, title in hits:
        if len(findings) >= max_pages * 3:
            break
        text = fetchlib.fetch(url)
        if not text:
            continue
        stype = "primary_source" if is_primary_source(url) else "web"
        cit = Citation(url=url, title=title, source_type=stype)
        findings.extend(extract(question, text, cit, branch_id=branch_id))
    return findings


def seek_structured(question: str, domains: list, *, branch_id: str = "main",
                    per_domain: int = 2, recency_years: int | None = None,
                    case_anchor: str = "") -> list:
    """Targeted pass over curated authoritative domains (source registry).
    Tags findings `structured_source`. Returns list[Finding].

    QUERY HYGIENE (2026-07-27): this lane used to send the RAW investigator lead
    ('Verify the identity, current status ... : Nuno Loureiro') straight to the search API — the
    boilerplate confuses the relevance model, and a BARE person name matches nothing on gov domains
    (they have no page titled for an individual). Fix: strip the scaffolding, and query the registry
    with the CASE TOPIC (what gov/official sites actually index: the inquiry, hearings, agency
    reports) rather than a name. `case_anchor` carries those distinctive case terms from the director;
    without it we fall back to the stripped lead. (Firecrawl over gov domains is precise-but-sparse by
    nature — Exa's neural index returned more but looser matches; fewer authoritative hits is honest,
    not broken.)"""
    if not domains:
        return []
    from .. import search_queries as _sq
    payload = _sq.strip_instructions(question) or question
    anchor = case_anchor or _CASE_ANCHOR   # explicit arg wins; else the run-scoped anchor
    # gov/official domains answer TOPIC queries, not names — anchor a short person payload to the case
    if anchor and len(payload.split()) <= 4:
        q = f"{payload} {anchor}".strip()
    else:
        q = payload
    findings = []
    try:
        for url, title in web_search(q, num_results=len(domains) * per_domain,
                                     include_domains=domains,
                                     recency_years=recency_years):   # Firecrawl-primary
            text = fetchlib.fetch(url)
            if not text:
                continue
            cit = Citation(url=url, title=title, source_type="structured_source")
            findings.extend(extract(question, text, cit, branch_id=branch_id))
    except Exception:
        pass
    return findings


def seek(question: str, *, branch_id: str = "main", max_pages: int = 4,
         recency_years: int | None = None) -> list:
    """Hunt the open web for a targeted question. Returns list[Finding].
    Records which domains were fetched (used by post-flight credibility update)."""
    # QUERY ADAPTER (2026-07-21): never ship our internal investigator scaffolding to a search API.
    # 'Verify the identity, current status, and documented cause or outcome ... : Monica Reza' was
    # ~130 chars of boilerplate around a ~20-char payload, and it returned people-search spam. Strip
    # it, then fan out a few angles and UNION the hits — one phrasing = one chance at recall.
    from .. import search_queries as _sq
    _qs = _sq.for_engine([question], "web")
    _payload = _qs[0] if _qs else question
    # angle fan-out ONLY for short entity payloads (a stripped person/org name) — appending
    # 'cause of death' to a long topical question is junk (Noor). Topical leads go as-is.
    if len(_payload.split()) <= 5:
        # NAME + ANGLE fan-out via the adapter's canonical angle list (person_queries) — not an inline
        # copy that drifts (audit: the real function sat orphaned while a hand-list shadowed it).
        _variants = _sq.person_queries(_payload, context=_anchor_for(_payload), max_q=4)
    else:
        # long topical lead: Exa is neural so the prose works, but a couple of keyword-register
        # variants materially widen recall (audit: one phrasing = one chance at recall).
        _variants = [_payload] + (_sq.plan_queries(_payload, engine="web", n=2) or [])
    _hits, _seen = [], set()
    for _v in _variants[:4]:
        try:
            for _u, _t in web_search(_v, num_results=max_pages + 2, recency_years=recency_years):  # Firecrawl-primary
                if _u not in _seen:
                    _seen.add(_u)
                    _hits.append((_u, _t))
        except Exception:
            continue
    findings = []
    for url, title in _hits:
        if len(findings) >= max_pages * 3:
            break
        text = fetchlib.fetch(url)
        if not text:
            continue
        citation = Citation(url=url, title=title, source_type="web")
        new = extract(question, text, citation, branch_id=branch_id)
        findings.extend(new)
    return findings
