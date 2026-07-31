"""Authoritative source registry (the kept kernel of the Data Harvester idea).

Steers Seeker toward curated high-value structured sources for a topic instead
of trusting generic search ranking. Feeds Exa `includeDomains` + the existing
fetch layer — NO Playwright, no hand-maintained CSS selectors (brittle), no new
organ. Findings are tagged `structured_source` but still go through pre/post-flight
(v11 spine: authoritative != unquestioned — a source is a sensor, not truth).

Lean start (Ray): 2 topic buckets. Extend the registry as it proves out.
"""
from __future__ import annotations

REGISTRY = {
    "ai_research": {
        "keywords": ["ai research", "llm", "inference", "language model", "machine "
                     "learning", "transformer", "fine-tun", "embedding", "quantiz",
                     "open-weight", "open weight", "gpu", "model routing", "distill"],
        "domains": ["arxiv.org", "huggingface.co"],
    },
    "regulation_finance": {
        "keywords": ["revenue", "sec ", "regulation", "filing", "financial", "earnings",
                     "enterprise", "pricing", "monetization", "monetize", "business "
                     "model", "arr", "profit", "subscription"],
        "domains": ["sec.gov", "federalregister.gov"],
    },
    # Medical/health peer-reviewed lane — the "well-supported" half of a health topic.
    "medical_health": {
        "keywords": ["covid", "long covid", "disease", "syndrome", "clinical", "patient",
                     "treatment", "therapy", "symptom", "diagnos", "vaccine", "infection",
                     "trial", "medical", "health", "epidemiolog", "pathophysiolog",
                     "immune", "neurolog"],
        "domains": ["pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "nih.gov", "who.int",
                    "nature.com", "thelancet.com", "nejm.org", "bmj.com", "jamanetwork.com",
                    "cochranelibrary.com", "medrxiv.org", "cdc.gov"],
    },
    # Government / law-enforcement / court / public-records lane — the authoritative half of any
    # case involving federal agencies, investigations, legislation, or litigation. Added 2026-07-19
    # after the missing-scientists run: a case with a House Oversight inquiry + FBI involvement matched
    # NO topic bucket, so the structured lane fetched nothing (came back DEAD). These are legally-public
    # records (Congress, courts, agencies, FOIA reading rooms) reachable via the existing Firecrawl/Jina
    # fetch — no scraping of anything non-public. This is the retrieval floor the Pattern-Claim organ
    # stands on: you cannot adjudicate a conspiracy claim without the official record to check it against.
    "government_legal": {
        "keywords": ["fbi", "cia", "nsa", "doj", "justice department", "law enforcement",
                     "police", "sheriff", "homicide", "missing person", "disappear", "investigation",
                     "congress", "senate", "house ", "oversight", "committee", "subpoena", "hearing",
                     "testimony", "federal", "agency", "classified", "national security", "pentagon",
                     "defense department", "court", "lawsuit", "indictment", "docket", "filing",
                     "prosecut", "trial", "verdict", "foia", "public record", "coroner", "medical examiner",
                     "los alamos", "sandia", "nasa", "jpl", "scientist", "researcher", "whistleblow"],
        "domains": ["congress.gov", "govinfo.gov", "oversight.house.gov", "judiciary.house.gov",
                    "justice.gov", "fbi.gov", "vault.fbi.gov", "courtlistener.com", "supremecourt.gov",
                    "uscourts.gov", "federalregister.gov", "gao.gov", "oig.justice.gov", "dni.gov",
                    "archives.gov", "defense.gov", "state.gov", "ntsb.gov", "nasa.gov", "lanl.gov"],
    },
    # Social/viral lane — the CONTESTED, narrative, engagement half. Gated: only fires
    # when the question explicitly reaches for the viral/social/controversy layer, so it
    # never pollutes a purely technical topic. Pulling these ALONGSIDE the peer-reviewed
    # lane is also what lets the disagreement detector actually fire (consensus vs dissent).
    "social_viral": {
        "keywords": ["viral", "conspiracy", "misinformation", "social media", "narrative",
                     "engagement", "went viral", "controvers", "debate", "public opinion",
                     "reddit", "twitter", "tiktok", "influencer", "advocacy"],
        "domains": ["reddit.com", "x.com", "twitter.com", "youtube.com", "tiktok.com",
                    "substack.com", "medium.com"],
    },
}


def target_domains(question: str) -> list:
    """Return curated authoritative domains matching the question's topic(s)."""
    q = (question or "").lower()
    hits = set()
    for cfg in REGISTRY.values():
        if any(k in q for k in cfg["keywords"]):
            hits.update(cfg["domains"])
    return sorted(hits)
