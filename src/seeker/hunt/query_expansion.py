"""Transcript-driven query expansion (Phase 1.5 — the practitioner-route unlock).

YouTube practitioners name specific tools, tactics, and terms a top-down question
never reaches. This module mines the transcripts for those, turns them into
concrete NEW search queries, and hunts those routes — pushing Seeker into
non-obvious territory it would not otherwise explore.

Spine: expansion queries are search DIRECTIONS extracted from external sources,
then hunted and vetted like any finding. No self-grading. Cost-bounded.
"""
from __future__ import annotations

import requests

from .. import config
from ..models import Citation
from ..memory.gap_detector import _cheap_json
from ..recon.extractor import extract
from . import seeker_agent
from .fetch import fetch

_MAX_DIRECTIONS = 4
_RESULTS_PER = 2


def extract_directions(transcripts: list, question: str,
                       max_dirs: int = _MAX_DIRECTIONS) -> list:
    """Mine transcripts for SPECIFIC, non-obvious search queries to run next."""
    if not transcripts:
        return []
    blob = "\n\n".join(f"[{t.get('title','')}]\n{t.get('text','')[:2500]}"
                       for t in transcripts[:4])
    prompt = (
        "Below are YouTube transcripts where practitioners discuss this question:\n"
        f"QUESTION: {question}\n\n"
        f"Extract up to {max_dirs} SPECIFIC, non-obvious search queries a researcher "
        "should run next — name the concrete tools, tactics, niche approaches, or terms "
        "the speakers actually mention that are NOT obvious from the original question. "
        "Avoid generic rephrasings. Return STRICT JSON {\"queries\": [\"...\"]}.\n\n"
        "TRANSCRIPTS:\n" + blob)
    data = _cheap_json(prompt)
    out = [q.strip() for q in data.get("queries", [])
           if isinstance(q, str) and q.strip()]
    return out[:max_dirs]


def extract_cited_sources(transcripts: list, question: str,
                          max_leads: int = _MAX_DIRECTIONS) -> list:
    """Mine transcripts for the SOURCES they cite — citation-chaining leads.

    Where `extract_directions` pulls topic ideas, this pulls the actual source
    ATTRIBUTIONS a speaker names ("the New York Times reported in 2022 that ...",
    "a Lancet study found ...", "this Substack posted the data"). Those are a map
    of WHERE the evidence lives — the transcript becomes a guide for hunting the
    web. Each lead is hunted and vetted like any finding (spine: a named source is
    still a sensor, not truth).
    """
    if not transcripts:
        return []
    blob = "\n\n".join(f"[{t.get('title','')}]\n{t.get('text','')[:2500]}"
                       for t in transcripts[:4])
    prompt = (
        "Below are YouTube transcripts discussing this question:\n"
        f"QUESTION: {question}\n\n"
        f"Extract up to {max_leads} SPECIFIC SOURCES the speakers CITE or ATTRIBUTE a "
        "claim to — a named publication/outlet, study, author, dataset, or website they "
        "say posted or reported something. For each, capture what makes it findable. "
        "Ignore vague references ('some studies', 'people say'). Only concrete, named, "
        "chase-able sources.\n"
        'Return STRICT JSON {"sources": [{"outlet": "...", "date": "", "claim": "...", '
        '"url": ""}]}. Use "" for anything not stated.\n\n'
        "TRANSCRIPTS:\n" + blob)
    data = _cheap_json(prompt)
    leads = []
    for s in data.get("sources", []):
        if not isinstance(s, dict):
            continue
        outlet = str(s.get("outlet", "")).strip()
        claim = str(s.get("claim", "")).strip()
        if not outlet and not s.get("url"):
            continue  # nothing chase-able
        leads.append({"outlet": outlet, "date": str(s.get("date", "")).strip(),
                      "claim": claim, "url": str(s.get("url", "")).strip()})
    return leads[:max_leads]


def chase_sources(leads: list, *, question: str = "", branch_id: str = "main",
                  recency_years: int | None = None) -> tuple:
    """Chase each cited-source lead: fetch a stated URL directly, else search for
    the named outlet + claim. Returns (findings, leads_used). Cost-bounded.

    Objective-relevance gate (Vera/Zara flag): before chasing, each lead is checked
    against the investigation `question` so chaining DEEPENS the goal instead of
    wandering into a rabbit hole. Reuses the fail-open `relevance_ok` gate — a gate
    outage never drops a lead (returns 'gate_error' -> kept)."""
    from ..recon.transcript_validator import relevance_ok
    findings, used = [], []
    for lead in leads:
        try:
            if question:  # gate the lead to the objective before spending on it
                probe = " ".join(x for x in (lead.get("outlet", ""),
                                             lead.get("claim", "")) if x)
                if probe and relevance_ok(probe, question) == "no":
                    continue  # off-objective lead — don't chase it
            hit_any = False
            url = lead.get("url", "")
            if url:  # the transcript named the actual link — fetch it directly
                text = fetch(url)
                if text:
                    cit = Citation(url=url, title=lead.get("outlet", "") or url,
                                   source_type="web")
                    findings.extend(extract(lead.get("claim") or url, text, cit,
                                            branch_id=branch_id))
                    hit_any = True
            else:    # no link — turn the attribution into a targeted search query
                query = " ".join(x for x in (lead.get("outlet", ""),
                                             lead.get("claim", ""),
                                             lead.get("date", "")) if x).strip()
                if not query:
                    continue
                for u, title in seeker_agent.exa_web_search(
                        query, num_results=_RESULTS_PER, recency_years=recency_years):
                    text = fetch(u)
                    if not text:
                        continue
                    cit = Citation(url=u, title=title, source_type="web")
                    findings.extend(extract(query, text, cit, branch_id=branch_id))
                    hit_any = True
            if hit_any:
                used.append(lead.get("outlet") or lead.get("url"))
        except Exception:
            continue
    return findings, used


def seek_counter_evidence(question: str, mm, *, branch_id: str = "main",
                          recency_years: int | None = None, max_claims: int = 3) -> list:
    """Actively hunt the OPPOSING side of the leading claims (Flag B real fix / H7).

    Disagreement can't be detected if only one side was ever retrieved — you can't find a
    contradiction that isn't in the map. So for the strongest current claims, deliberately
    search for evidence AGAINST them, fetch, and extract. Those opposing findings then let
    the controversy detector actually fire. Bounded + best-effort; a fetched counter-source
    is still a sensor, vetted like any finding."""
    from ..memory.confidence import standard_label
    hits = mm.query(question, branch_id=branch_id, top_k=10, node_kind="finding", hybrid=True)
    strong = [h for h in hits
              if standard_label(h.get("confidence_tier", "Speculative")) == "well-supported"]
    strong = (strong or hits)[:max_claims]
    findings: list = []
    for h in strong:
        claim = (h.get("text") or "").strip()
        if not claim:
            continue
        cq = ('evidence, studies, or expert criticism that dispute or contradict this claim: '
              f'"{claim[:180]}"')
        try:
            for url, title in seeker_agent.exa_web_search(
                    cq, num_results=2, recency_years=recency_years):
                text = fetch(url)
                if not text:
                    continue
                findings.extend(extract(cq, text,
                                        Citation(url=url, title=title, source_type="web"),
                                        branch_id=branch_id))
        except Exception:
            continue
    return findings


def mine_description_sources(question: str, *, branch_id: str = "main",
                             recency_years: int | None = None,
                             max_videos: int = 3, max_links: int = 6) -> list:
    """Video-description mining (Hunt upgrade H1). Creators paste the SOURCE links they used
    right in the description — instant, high-confidence access to primary sources (papers,
    filings, datasets) that spoken-mention chaining only hints at. Search videos, decode the
    description's source links, then fetch + extract those primaries. Bounded + best-effort."""
    from ..recon import youtube
    findings, seen, n = [], set(), 0
    try:
        vids = youtube.exa_youtube_search(question, num_results=max_videos,
                                          recency_years=recency_years)
    except Exception:
        return findings
    for vurl, _title in vids:
        if n >= max_links:
            break
        for link in youtube.description_links(vurl):
            if link in seen or n >= max_links:
                continue
            seen.add(link)
            try:
                text = fetch(link)
                if text:
                    findings.extend(extract(question, text,
                                            Citation(url=link, title=link, source_type="web"),
                                            branch_id=branch_id))
                    n += 1
            except Exception:
                continue
    return findings


# source-looking hosts — a link into one of these is likely a PRIMARY reference
# (paper, filing, dataset) worth descending into, not just commentary
_SOURCE_HINTS = ("doi.org", "pubmed", "ncbi.nlm.nih.gov", "nature.com", "sciencedirect",
                 "springer", "wiley", "nejm.org", "thelancet", "bmj.com", "jamanetwork",
                 "academic.oup.com", "arxiv.org", "ssrn.com", "sec.gov", ".gov/", ".edu/")
# hosts that are almost never a cited primary source — don't spend a hop on them
_CHASE_NOISE = ("twitter.com", "x.com", "facebook.com", "instagram.com", "tiktok.com",
                "youtube.com", "youtu.be", "linkedin.com", "reddit.com", "amazon.",
                "patreon.com", "linktr.ee", "google.com/search", "wikipedia.org/wiki/Special",
                "creativecommons.org", "flourish.studio", "automeris.io", "webplotdigitizer")


def _outbound_links(text: str) -> list:
    """Pull the source links a fetched page ITSELF references. Jina returns markdown,
    so `[text](url)` citations survive; also catch bare URLs. Primary-looking links
    (papers/filings/datasets) are ordered first so a bounded hop spends on them."""
    import re
    urls, seen = [], set()
    cands = re.findall(r'\]\((https?://[^\s)]+)\)', text or "")      # markdown links
    cands += re.findall(r'(?<![\(<"])https?://[^\s)>\]"]+', text or "")  # bare URLs
    for u in cands:
        u = u.rstrip(".,);]")
        low = u.lower()
        if u in seen or any(n in low for n in _CHASE_NOISE):
            continue
        seen.add(u)
        urls.append(u)
    urls.sort(key=lambda u: 0 if any(h in u.lower() for h in _SOURCE_HINTS) else 1)
    return urls


def _cited_leads_wide(text: str, question: str, max_leads: int) -> list:
    """Like `extract_cited_sources` but over a WIDE window of a single page — citations live
    in the intro AND the reference list at the very end, which the 2.5k-char shared path
    never sees. Samples the head (where secondary sources cite primaries) and the tail
    (the reference list) so a real reference gets caught (H6's fix for scholarly pages)."""
    text = text or ""
    if len(text) > 12000:  # head + tail: the citing intro and the reference list
        blob = text[:8000] + "\n...\n" + text[-4000:]
    else:
        blob = text
    prompt = (
        "Below is a source PAGE discussing this question:\n"
        f"QUESTION: {question}\n\n"
        f"Extract up to {max_leads} SPECIFIC SOURCES this page CITES or references — a named "
        "study, paper, author+year, dataset, or outlet it attributes a claim to (include the "
        "reference list). For each capture what makes it findable.\n"
        'Return STRICT JSON {"sources": [{"outlet": "...", "date": "", "claim": "", "url": ""}]}. '
        'Use "" for anything not stated.\n\nPAGE:\n' + blob)
    data = _cheap_json(prompt)
    leads = []
    for s in data.get("sources", []):
        if isinstance(s, dict) and (str(s.get("outlet", "")).strip() or s.get("url")):
            leads.append({"outlet": str(s.get("outlet", "")).strip(),
                          "date": str(s.get("date", "")).strip(),
                          "claim": str(s.get("claim", "")).strip(),
                          "url": str(s.get("url", "")).strip()})
    return leads[:max_leads]


def _resolve_doi(outlet: str, claim: str, date: str = "") -> str:
    """Turn a NAMED scholarly citation ('NEJM 2022, author, title') into a followable URL
    via Crossref (free, keyless, public). This is what makes recursive chaining work on
    scholarly pages, which cite by reference — not link. Returns a doi.org URL or ''."""
    query = " ".join(x for x in (outlet, claim, date) if x).strip()
    if len(query) < 12:  # too vague to resolve to a specific paper
        return ""
    try:
        r = requests.get("https://api.crossref.org/works",
                         params={"query.bibliographic": query, "rows": 1},
                         headers={"User-Agent": "Seeker/1.0 (research agent)"},
                         timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        items = (r.json().get("message", {}) or {}).get("items", [])
        doi = items[0].get("DOI") if items else None
        return f"https://doi.org/{doi}" if doi else ""
    except Exception:
        return ""


def _page_next_urls(text: str, url: str, question: str, max_leads: int) -> list:
    """The next hop's candidate URLs from a fetched page. Two robust signals, combined:
    (1) the LLM names the SOURCES the page cites (works even when a reader strips links or
    we fell back to a link-less archive snapshot), and (2) any real outbound links present.
    Named-but-unlinked sources are resolved to a URL by a targeted search."""
    urls, seen = [], set()
    for u in _outbound_links(text):  # cheap: real links, if the reader kept them
        if u != url and u not in seen:
            seen.add(u)
            urls.append(u)
    # robust: the sources the page ATTRIBUTES claims to (survives link-stripping),
    # scanned over a WIDE window so the reference list is actually seen
    leads = _cited_leads_wide(text, question, max_leads)
    for lead in leads:
        u = lead.get("url", "")
        if not u:  # named but unlinked — resolve it. Crossref (scholarly DOI) first, then search
            u = _resolve_doi(lead.get("outlet", ""), lead.get("claim", ""),
                             lead.get("date", ""))
        if not u:
            query = " ".join(x for x in (lead.get("outlet", ""), lead.get("claim", ""),
                                         lead.get("date", "")) if x).strip()
            if not query:
                continue
            try:
                hits = seeker_agent.exa_web_search(query, num_results=1)
            except Exception:
                hits = []
            u = hits[0][0] if hits else ""
        if u and u != url and u not in seen:
            seen.add(u)
            urls.append(u)
    urls.sort(key=lambda u: 0 if any(h in u.lower() for h in _SOURCE_HINTS) else 1)
    return urls


def chase_recursive(question: str, seed_urls: list, *, branch_id: str = "main",
                    recency_years: int | None = None, depth: int = 1,
                    max_per_hop: int = 3, max_total: int = 6) -> list:
    """Bounded recursive citation-chaining (Hunt upgrade H6). A master researcher doesn't
    stop at the first source — they follow that source's OWN references back toward the
    origin. This reuses the proven citation-extraction path (`extract_cited_sources`) so it
    keeps working even when a page's links get stripped, descends depth-capped and
    relevance-gated at each hop, with a hard total-fetch budget so it can't rabbit-hole. A
    fetched page is kept + descended only if it's genuinely on-topic (relevance gate,
    fail-open); every hop is still a sensor, vetted like any finding. Loop-safe."""
    from ..recon.transcript_validator import relevance_ok
    findings: list = []
    visited: set = set(seed_urls)  # don't re-fetch the seeds themselves
    budget = [0]

    def _walk(text: str, d: int) -> None:
        if d <= 0 or budget[0] >= max_total:
            return
        for url in _page_next_urls(text, "", question, max_per_hop)[:max_per_hop]:
            if budget[0] >= max_total:
                return
            if url in visited:
                continue
            visited.add(url)
            try:
                nxt = fetch(url)
            except Exception:
                continue
            if not nxt:
                continue
            budget[0] += 1
            if relevance_ok(nxt, question) == "no":  # off-topic hop — don't keep or descend
                continue
            findings.extend(extract(question, nxt,
                                    Citation(url=url, title=url, source_type="web"),
                                    branch_id=branch_id))
            _walk(nxt, d - 1)  # follow THIS source's own references, one level deeper

    for su in seed_urls:
        if budget[0] >= max_total:
            break
        try:
            t = fetch(su)
        except Exception:
            t = None
        if t:
            _walk(t, depth)
    return findings


def _record_gated_lead(mm, work: dict, question: str, branch_id: str) -> None:
    """A paywalled paper isn't a dead end — it's a KNOWN lead. Record it as a 'gated' dim
    node on the map (Chris's ask): the map remembers 'useful evidence may live here, access
    to reveal' instead of silently dropping it. Best-effort."""
    if not mm or not work:
        return
    from ..models import GapNode
    from . import scholar
    title = (work.get("title") or "untitled")[:120]
    # Only record a gated lead that's actually ON-TOPIC — a paywalled paper's reference list is
    # full of shared METHODS/TOOL papers (e.g. "PLINK: A Tool Set for...") that aren't substantive
    # leads for THIS question. Cheap relevance gate on the title; fail-open (record on gate error).
    try:
        from ..recon.transcript_validator import relevance_ok
        if title and relevance_ok(title, question) == "no":
            return
    except Exception:
        pass
    url = scholar.primary_url(work)
    q = (f"⚠️ PAYWALLED LEAD — '{title}' ({url}) may hold evidence for: "
         f"{question[:80]}. Locked; access to reveal or find a review.")
    try:
        mm.upsert_gap(GapNode(question=q, gap_type="gated", status="dim", branch_id=branch_id))
    except Exception:
        pass


def seek_secondary_coverage(paper_title: str, question: str, *, branch_id: str = "main",
                            recency_years: int | None = None, max_results: int = 2) -> list:
    """When a primary paper is locked, find who REVIEWED or summarized it (Chris's ask) —
    the open web surfaces blog write-ups, Reddit threads, and YouTube explainers of a
    specific paper. Those are SECONDARY sensors (tagged `source_type="secondary_review"`,
    never weighted like the primary — Vera), relevance-gated and bounded."""
    if not paper_title or len(paper_title) < 8:
        return []
    from ..recon.transcript_validator import relevance_ok
    findings: list = []
    q = f'"{paper_title}" review OR summary OR explained OR discussion OR critique'
    try:
        for url, title in seeker_agent.exa_web_search(q, num_results=max_results,
                                                      recency_years=recency_years):
            text = fetch(url)
            if not text or relevance_ok(text, question) == "no":
                continue
            findings.extend(extract(question, text,
                                    Citation(url=url, title=title,
                                             source_type="secondary_review"),
                                    branch_id=branch_id))
    except Exception:
        pass
    return findings


def chase_citation_graph(question: str, seed_urls: list, *, mm=None, branch_id: str = "main",
                         recency_years: int | None = None, depth: int = 1,
                         max_refs: int = 6, max_total: int = 10) -> tuple:
    """H6 v2 — recursive citation-chaining on the OpenAlex scholarly graph (legal, free).

    The scrape-based v1 hit two walls: paywalls, and only ever learning a JOURNAL name.
    This rides the citation graph instead: a seed resolves to a work, whose references are
    SPECIFIC papers (not names). For each we read the LEGAL text — open-access full text if
    it exists, else the abstract (enough for the key finding). If a paper is closed with no
    abstract, we DON'T bypass it (Ghost): we drop a gated-lead marker on the map AND go find
    who reviewed it. Depth-capped, relevance-gated, hard fetch budget, loop-safe.
    Returns (findings, gated_titles)."""
    from ..recon.transcript_validator import relevance_ok
    from . import scholar
    findings: list = []
    gated: list = []
    visited: set = set()
    budget = [0]

    def _walk(work: dict, d: int) -> None:
        if d <= 0 or budget[0] >= max_total:
            return
        for ref in scholar.fetch_works(scholar.referenced_ids(work, limit=max_refs)):
            if budget[0] >= max_total:
                return
            wid = ref.get("id", "")
            if not wid or wid in visited:
                continue
            visited.add(wid)
            budget[0] += 1
            text, url, kind = scholar.readable_text(ref)
            title = ref.get("title") or ""
            if kind == "gated" or not text:
                _record_gated_lead(mm, ref, question, branch_id)
                gated.append(title)
                findings.extend(seek_secondary_coverage(
                    title, question, branch_id=branch_id, recency_years=recency_years))
                continue
            if relevance_ok(text, question) == "no":
                continue
            stype = "primary_source" if kind == "oa_fulltext" else "abstract"
            findings.extend(extract(question, text,
                                    Citation(url=url, title=title, source_type=stype),
                                    branch_id=branch_id))
            _walk(ref, d - 1)  # descend into THIS paper's own references

    # CIRCUIT BREAKER (2026-07-19): on a NEWS/people case the seeds are article headlines, none of
    # which resolve to OpenAlex papers — and if OpenAlex is rate-limiting, each miss burns retries.
    # A run once spent 10 min here (watchdog aborted it). Cap the attempts, and bail after a few
    # consecutive misses: either this isn't an academic case or OpenAlex is throttling us — in both
    # cases more attempts won't help THIS run. Fail-open (whatever we found so far stands).
    misses = 0
    for su in seed_urls[:12]:
        if budget[0] >= max_total or misses >= 3:
            break
        w = scholar.resolve(su)
        if w:
            misses = 0
            _walk(w, depth)
        else:
            misses += 1
    return findings, gated


def expand_search(directions: list, *, branch_id: str = "main",
                  recency_years: int | None = None) -> tuple:
    """Hunt each expansion direction (Exa web -> fetch -> extract).
    Returns (findings, directions_used)."""
    findings, used = [], []
    for d in directions:
        try:
            hit_any = False
            for url, title in seeker_agent.exa_web_search(
                    d, num_results=_RESULTS_PER, recency_years=recency_years):
                text = fetch(url)
                if not text:
                    continue
                cit = Citation(url=url, title=title, source_type="web")
                findings.extend(extract(d, text, cit, branch_id=branch_id))
                hit_any = True
            if hit_any:
                used.append(d)
        except Exception:
            continue
    return findings, used
