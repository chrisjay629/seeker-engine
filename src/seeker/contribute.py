"""Contribution lane (Chris's design, 2026-07-30) — ask Perplexity what it can ADD to the map.

NOT a critic. Chris was specific about this and the distinction matters: Perplexity is not asked to
evaluate Seeker's work, it is asked whether it holds documented detail the map does not. A judge
would cap Seeker at the judge's ceiling — Seeker could never be better than the thing grading it.
A contributor is just another sensor, like Firecrawl or the podcast lane, and adds without bounding.

WHY IT IS WORTH HAVING. The v20 benchmark found no facts Perplexity knew that Seeker had not already
gathered — but Perplexity reached them in 6 minutes with 18 citations, and it framed several cases
in ways our corpus had not (the McCasland case as distinguishable from the resolved deaths). A
second retrieval path with a different index will sometimes hold a document ours never saw. That is
worth one call at the end of a run.

THE THREE GUARDS, because this lane imports text we did not gather:

  UNVERIFIED ON ENTRY — everything lands as Speculative. A contributed claim may never set a
  person's status or documented cause; it has to be corroborated by our own sources first, through
  the normal consolidation path. Perplexity is a lead, not a witness (Vera).

  CLAIMS, NEVER PROSE — the response is broken into atomic claims and normalized before anything
  touches the map. Perplexity's deep-research output carries exactly the framing the voice gate
  exists to strip ("a string of mysterious deaths"); importing its sentences would reintroduce it
  wholesale (Ghost).

  NAMESAKE-SCREENED — contributed claims pass the same identity check as everything else. A second
  search engine is a second chance to pull in the wrong Joshua LeBlanc.

And a novelty test, because a contributor that hands back what we already hold is not adding, it is
padding: anything closely matching an existing claim is dropped, and the drop count is reported.
"""
from __future__ import annotations

import os as _os
import re as _re

import requests as _requests

from . import config as _config
from . import identity as _identity
from .memory.gap_detector import extract_claims as _extract_claims
from .models import Citation, Finding

_URL = "https://api.perplexity.ai/chat/completions"
# Their research agent, not the cheap lane: this fires ONCE per run, at the end, so the expensive
# model is the right call — a fast shallow answer is the one thing we already have plenty of.
_MODEL = _os.environ.get("PERPLEXITY_CONTRIBUTE_MODEL", "sonar-deep-research")


# Claims ABOUT the answer rather than about the case. The first live run returned 19 "new" claims
# and 11 were this: "The response strictly includes only specific, checkable factual details",
# "Statements relying on inference or opinion are omitted", "Each factual statement is followed by
# bracketed source indices". Perplexity's deep-research output opens with a methodology preamble,
# the claim extractor read it as content, and the novelty filter passed every line because a
# sentence about the response genuinely is not in our map. Self-description is not evidence.
_META = _re.compile(
    r"\b(the response|this response|the search results|the user'?s? (file|summary|list)|"
    r"the existing summary|these new facts|the new facts|the factual material|"
    r"are excluded|are omitted|is omitted|not previously (noted|included)|"
    r"more (specific|formal) than|bracketed source|source indices|"
    r"sources referenced|this (summary|answer)|previously generic)\b", _re.I)


def _is_meta(claim: str) -> bool:
    """Is this a claim about the ANSWER rather than about the case?"""
    return bool(_META.search(claim or ""))


def _norm(s: str) -> set:
    return {w for w in _re.findall(r"[a-z]{4,}", (s or "").lower())}


def _is_new(claim: str, existing: list, *, overlap: float = 0.6) -> bool:
    """Does this claim say something the map does not already hold?

    Word-overlap rather than embeddings: it runs offline, costs nothing, and the failure mode is
    the safe one — a paraphrase we wrongly keep enters as UNVERIFIED and gets deduped by
    consolidation anyway, whereas a missed novel claim is gone for good."""
    c = _norm(claim)
    if len(c) < 4:
        return False
    for e in existing:
        ew = _norm(e)
        if ew and len(c & ew) / max(1, min(len(c), len(ew))) >= overlap:
            return False
    return True


def _ask(prompt: str, timeout: int = 900) -> tuple:
    r = _requests.post(
        _URL,
        headers={"Authorization": f"Bearer {_config.PERPLEXITY_API_KEY}",
                 "Content-Type": "application/json"},
        json={"model": _MODEL, "messages": [{"role": "user", "content": prompt}]},
        timeout=timeout)
    r.raise_for_status()
    d = r.json()
    text = d["choices"][0]["message"]["content"]
    urls = [(sr.get("url") or "") for sr in (d.get("search_results") or [])] or \
           [u for u in (d.get("citations") or []) if isinstance(u, str)]
    return text, [u for u in urls if u]


def contribute(question: str, entities: list, existing_claims: list, *,
               cards: dict | None = None, branch_id: str = "main",
               max_claims: int = 20) -> dict:
    """Ask for documented detail the map lacks. Returns
    {findings, added, dropped_duplicate, dropped_namesake, sources, raw}.

    Fail-open to an empty contribution: this lane is a bonus at the end of a run and must never be
    able to take a completed investigation down with it."""
    out = {"findings": [], "added": 0, "dropped_duplicate": 0, "dropped_namesake": 0,
           "dropped_meta": 0,
           "sources": [], "raw": "", "error": ""}
    try:
        # Show what we already have so the ask is genuinely for the GAP. Capped: a prompt carrying
        # 500 claims buries the instruction, and the novelty filter is the real dedup anyway.
        known = "\n".join(f"- {c}" for c in existing_claims[:120])
        prompt = (
            "I have an existing research file on the question below. I am NOT asking you to review "
            "or critique it. I am asking one thing: do you have DOCUMENTED DETAILS that are NOT in "
            "it?\n\n"
            "Rules for your answer:\n"
            "- Report only specific, checkable facts: dates, locations, employers, official "
            "findings, named agencies, case numbers, documents.\n"
            "- Say where each came from.\n"
            "- If a detail already appears in WHAT I HAVE, skip it. Do not restate my file.\n"
            "- Do NOT speculate, theorise, or characterise the cases as a pattern. Facts only.\n"
            "- If you have nothing to add, say exactly that.\n\n"
            f"QUESTION:\n{question}\n\n"
            f"PEOPLE:\n{', '.join(str(e) for e in (entities or [])[:30])}\n\n"
            f"WHAT I HAVE:\n{known}\n")
        text, urls = _ask(prompt)
        out["raw"], out["sources"] = text, urls
        if not text.strip():
            return out

        cites = [Citation(url=u, source_type="perplexity") for u in urls[:40]]
        for item in _extract_claims(text, f"perplexity/{_MODEL}", max_claims=max_claims,
                                    source_type="perplexity"):
            claim = getattr(item, "claim", None) or getattr(item, "text", "") or str(item)
            if _is_meta(claim):
                out["dropped_meta"] += 1
                continue
            if not _is_new(claim, existing_claims):
                out["dropped_duplicate"] += 1
                continue
            if cards:
                bad = False
                for name, card in cards.items():
                    surname = str(name).split()[-1].lower()
                    if surname in claim.lower() and _identity.conflict(claim, card)[0] == "hard":
                        out["dropped_namesake"] += 1
                        bad = True
                        break
                if bad:
                    continue
            out["findings"].append(Finding(
                claim=claim, citations=cites[:6],
                confidence_tier="Speculative",       # UNVERIFIED on entry, always
                branch_id=branch_id))
        out["added"] = len(out["findings"])
    except Exception as e:
        out["error"] = repr(e)[:160]
    return out


def format_contribution(res: dict) -> str:
    if res.get("error"):
        return f"— CONTRIBUTION (Perplexity) — skipped: {res['error']}"
    lines = [f"— CONTRIBUTION (Perplexity) — {res['added']} new claim(s), "
             f"{res['dropped_duplicate']} already known, "
             f"{res['dropped_namesake']} namesake-blocked, "
             f"{res.get('dropped_meta', 0)} self-description, {len(res['sources'])} sources"]
    for f in res.get("findings", [])[:10]:
        lines.append(f"   + {f.claim[:110]}")
    return "\n".join(lines)
