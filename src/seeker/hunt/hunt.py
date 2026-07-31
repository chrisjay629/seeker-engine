"""The merged fetch-then-verify loop (brief 06) — now with a YouTube channel.

pre-flight challenge -> Seeker fetch (web pages via Jina/Firecrawl AND YouTube
transcripts via the Recon YouTube channel) -> upsert findings to the Memory Map
-> post-flight challenge. Verification external on both ends (spine).

Every source hit is recorded (url, type, title) so an investigation can show
exactly where it looked (Luna's visibility flag).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..memory.memory_map import MemoryMap
from ..recon import youtube
from . import adversarial, seeker_agent, query_expansion, source_registry


@dataclass
class HuntResult:
    question: str
    survived_preflight: bool
    preflight_scores: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    n_upserted: int = 0
    n_merged: int = 0          # near-duplicates folded into existing nodes
    n_nested: int = 0          # collaborative duplicates nested (corroboration kept)
    novelty: dict = field(default_factory=dict)   # {novel/incremental/redundant} counts
    n_web: int = 0
    n_primary: int = 0         # findings from primary sources (H4)
    n_youtube: int = 0
    n_expansion: int = 0
    n_chased: int = 0          # findings from chasing sources cited in transcripts
    n_structured: int = 0
    structured_domains: list = field(default_factory=list)
    expansions: list = field(default_factory=list)   # search directions from transcripts
    chased_leads: list = field(default_factory=list) # cited sources chased from transcripts
    sources: list = field(default_factory=list)      # [{"url","type","title"}]
    post: object = None
    note: str = ""


def _collect_sources(findings: list) -> list:
    seen, out = set(), []
    for f in findings:
        for c in getattr(f, "citations", []):
            url = getattr(c, "url", "")
            if url and url not in seen:
                seen.add(url)
                out.append({"url": url, "type": getattr(c, "source_type", "web"),
                            "title": getattr(c, "title", "")})
    return out


def hunt(question: str, *, branch_id: str = "main", max_pages: int = 3,
         youtube_results: int = 3, with_youtube: bool = True, with_podcast: bool = True,
         with_expansion: bool = True, recency_years: int | None = None,
         entities: list | None = None) -> HuntResult:
    mm = MemoryMap()

    pre = adversarial.pre_flight(question, mm=mm, branch_id=branch_id)
    if not pre.survived:
        return HuntResult(question=question, survived_preflight=False,
                          preflight_scores=pre.scores,
                          note=f"rejected pre-flight: {pre.reason}")

    # Independent retrieval lanes — web, primary-source (H4), curated-registry (structured), and the
    # spoken-word lanes (H1) — have NO dependency on each other, so fire them CONCURRENTLY instead of
    # serially (task #20 lever 2). Bounded pool; the rate governor caps per-provider concurrency, so
    # this multiplies with the lead parallelism without self-throttling. The dependent steps
    # (transcript expansion, citation-graph) run AFTER, since they consume these results.
    domains = source_registry.target_domains(question)   # cheap/sync — seek_structured needs it

    def _web():
        return seeker_agent.seek(question, branch_id=branch_id, max_pages=max_pages,
                                 recency_years=recency_years)
    def _fc():   # standalone Firecrawl excerpt-first lane — only a SEPARATE engine when Exa is
        # primary. When Firecrawl is primary (default post-migration) the _web lane ALREADY searches
        # Firecrawl, so running this too would search+pay Firecrawl twice per hunt (Marcus).
        import os as _os
        if _os.environ.get("SEEKER_SEARCH_PRIMARY", "firecrawl").strip().lower() != "exa":
            return []
        try:
            return seeker_agent.seek_firecrawl(question, branch_id=branch_id,
                                               max_pages=max_pages, recency_years=recency_years)
        except Exception:
            return []
    def _primary():   # H4 — go to the origin (paper/filing/dataset), tagged primary_source
        return seeker_agent.seek_primary(question, branch_id=branch_id,
                                         max_pages=max_pages, recency_years=recency_years)
    def _structured():   # curated high-value domains
        return seeker_agent.seek_structured(question, domains, branch_id=branch_id,
                                            recency_years=recency_years)
    def _yt():
        if with_youtube:
            return youtube.gather(question, num_results=youtube_results, branch_id=branch_id,
                                  recency_years=recency_years, entities=entities)
        return ([], [])
    def _pod():   # gated: transcription is expensive; on for harvest+seed, off for per-lead hunts
        if not with_podcast:
            return []
        try:
            from ..recon import podcast
            # pass the roster: searching a person's NAME finds the show dedicated to the case (the
            # name-search fix was inert here before — hunt() never forwarded entities, so the flagship
            # podcast lane ran without the roster and returned 0 while it worked standalone).
            return podcast.gather(question, branch_id=branch_id, recency_years=recency_years,
                                  entities=entities)[0]
        except Exception:
            return []

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as _ex:
        _fw, _fp, _fs = _ex.submit(_web), _ex.submit(_primary), _ex.submit(_structured)
        _fyt, _fpod, _ffc = _ex.submit(_yt), _ex.submit(_pod), _ex.submit(_fc)
        web = _fw.result()
        primary = _fp.result()
        structured = _fs.result()
        yt, transcripts = _fyt.result()
        pod = _fpod.result()
        fc = _ffc.result()

    # transcript-driven query expansion — depends on transcripts, so runs AFTER the concurrent lanes
    exp, used_dirs = ([], [])
    chased, chased_leads = ([], [])
    desc = []
    if with_expansion and transcripts:
        dirs = query_expansion.extract_directions(transcripts, question)
        exp, used_dirs = query_expansion.expand_search(
            dirs, branch_id=branch_id, recency_years=recency_years)
        # citation-chaining — chase the SOURCES the transcripts actually cite (spoken mentions)
        leads = query_expansion.extract_cited_sources(transcripts, question)
        chased, chased_leads = query_expansion.chase_sources(
            leads, question=question, branch_id=branch_id, recency_years=recency_years)
        # description mining (H1) — the source LINKS creators paste in the description
        desc = query_expansion.mine_description_sources(
            question, branch_id=branch_id, recency_years=recency_years)

    # citation-graph chase (H6 v2) — follow the REFERENCES of the papers we found, via OpenAlex:
    # read legal abstracts / OA text of the specific works they cite. Paywalled dead-ends get a
    # 'gated' marker + a review search. Seed from BOTH primary-source AND structured (curated
    # registry, e.g. PubMed/NIH) findings — on scientific topics the real PAPER titles come from
    # the structured lane; the primary lane can be agency LANDING pages that don't resolve.
    cited_graph = []
    if with_expansion:
        # Seed by the paper's TITLE (OpenAlex resolves by title.search) or a DOI-bearing URL —
        # publisher LANDING urls (bmj.com/content/...) carry no parseable DOI.
        seeds = []
        for f in (primary + structured):
            if not f.citations:
                continue
            c = f.citations[0]
            seeds.append(c.title if (c.title and len(c.title) >= 12) else c.url)
        seeds = [s for s in dict.fromkeys(seeds) if s][:4]   # dedup, drop empties, cap
        if seeds:
            cited_graph, _gated = query_expansion.chase_citation_graph(
                question, seeds, mm=mm, branch_id=branch_id,
                recency_years=recency_years, depth=1, max_refs=5, max_total=6)

    findings = web + fc + primary + yt + pod + exp + chased + desc + cited_graph + structured
    # consolidate on ingest — merge near-duplicates instead of adding copies
    from ..memory.consolidation import upsert_findings_consolidated
    consol = upsert_findings_consolidated(mm, findings)
    post = adversarial.post_flight(question, findings, mm=mm, branch_id=branch_id)

    # Lateral reading (H3): fact-check up to 3 NEW, non-trusted, not-yet-checked source
    # domains by what OTHER sources say about them. Cached forever → self-limits and
    # amortizes to ~nothing. Skips the pre-vetted authoritative registry domains.
    try:
        from . import credibility
        from .fetch import domain_of
        trusted = set()
        for cfg in source_registry.REGISTRY.values():
            trusted.update(cfg.get("domains", []))
        ledger = credibility._load()
        done = 0
        for f in findings:
            if done >= 3:
                break
            for c in getattr(f, "citations", []):
                dom = domain_of(getattr(c, "url", ""))
                if dom and dom not in trusted and not ledger.get(dom, {}).get("lateral"):
                    credibility.lateral_read(dom)
                    ledger = credibility._load()
                    done += 1
                    break
    except Exception:
        pass

    return HuntResult(question=question, survived_preflight=True,
                      preflight_scores=pre.scores, findings=findings,
                      n_upserted=consol["distinct_added"], n_merged=consol["merged"],
                      n_nested=consol.get("nested", 0),
                      novelty=consol.get("novelty", {}),
                      n_web=len(web), n_youtube=len(yt),
                      n_expansion=len(exp), n_chased=len(chased),
                      n_structured=len(structured),
                      structured_domains=domains, expansions=used_dirs,
                      chased_leads=chased_leads,
                      sources=_collect_sources(findings), post=post,
                      note="hunt complete")
