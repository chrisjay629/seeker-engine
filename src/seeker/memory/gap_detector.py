"""Gap Detector (owned by Memory Map, brief 03).

Turns the Recon Pass's SEPARATE source responses into gap nodes via the
mechanical detection in 00-shared-context §4:

  1. claim extraction   — break each source response into atomic claims
  2. embed + cluster     — group claims by MEANING (cosine), mechanical
  3. stance within cluster — agree vs. contradict across independent sources
  4. contradiction -> disagreement gap; same-polarity -> corroboration (not a gap)

Spine note: clustering is pure threshold math. The stance step is an EXTERNAL
NLI-style judgment comparing *independent sources* to each other — not a model
grading its own output. No component here rates its own quality.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import requests
from pinecone import Pinecone

from .. import config
from ..models import GapNode

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_EMBED_MODEL = "llama-text-embed-v2"
_CLUSTER_THRESHOLD = 0.55


@dataclass
class ClaimItem:
    text: str
    source_label: str
    source_type: str = "llm"   # llm | perplexity | youtube | web — feeds
    #                            independence-weighting at promotion time


def _cheap_json(prompt: str, *, model: str | None = None) -> dict:
    """VOLUME-tier JSON call (default EXTRACTOR_MODEL) — grunt work: extraction, contradiction checks.
    Pass `model` to override; the verdict organs use _reason_json (the REASONING tier) instead."""
    try:
        r = requests.post(
            _OPENROUTER_URL,
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": model or config.EXTRACTOR_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"}},
            timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return {}


def _reason_json(prompt: str) -> dict:
    """REASONING-tier JSON call (REASONING_MODEL) for the verdict-deciding organs — synthesis, ACH,
    claim ledger, connections, disagreement, Pattern-Claim. Few calls per run; worth a stronger model
    (routing audit 2026-07-19). Same fail-open contract as _cheap_json."""
    return _cheap_json(prompt, model=config.REASONING_MODEL)


def extract_claims(text: str, source_label: str, max_claims: int = 8,
                   source_type: str = "llm") -> list:
    prompt = (
        "Break this answer into at most %d atomic factual claims (one assertion "
        "each, no hedging). Return STRICT JSON {\"claims\": [\"...\"]}. Do not "
        "judge quality.\n\nANSWER:\n%s" % (max_claims, text[:6000]))
    data = _cheap_json(prompt)
    return [ClaimItem(c.strip(), source_label, source_type)
            for c in data.get("claims", []) if isinstance(c, str) and c.strip()]


def _embed(texts: list) -> list:
    """Jina, not Pinecone inference (2026-07-28) — the integrated path is metered and its 5M
    monthly quota is exhausted. Delegates to memory_map._embed so every embedding in the system
    comes from ONE model in ONE vector space; two embedders would make similarity meaningless."""
    from .memory_map import _embed as _map_embed
    return _map_embed(texts)


def _cos(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _cluster(items: list, vecs: list) -> list:
    """Greedy cosine clustering. Returns list of index-lists."""
    clusters: list = []       # list of {"members":[idx], "centroid_idx":idx}
    for i, v in enumerate(vecs):
        best, best_sim = None, 0.0
        for c in clusters:
            sim = max(_cos(v, vecs[j]) for j in c)
            if sim > best_sim:
                best, best_sim = c, sim
        if best is not None and best_sim >= _CLUSTER_THRESHOLD:
            best.append(i)
        else:
            clusters.append([i])
    return clusters


def _stance(claims: list) -> str:
    """agree | contradict | mixed | single — EXTERNAL judgment across sources."""
    listing = "\n".join(f"- ({c.source_label}) {c.text}" for c in claims)
    prompt = (
        "These claims come from DIFFERENT independent sources on the same topic. "
        "Do they mostly AGREE, or do some CONTRADICT each other on substance "
        "(not wording)? Return STRICT JSON {\"relation\": \"agree|contradict|mixed\"}."
        "\n\nCLAIMS:\n" + listing)
    data = _cheap_json(prompt)
    rel = data.get("relation", "")
    return rel if rel in ("agree", "contradict", "mixed") else "agree"


@dataclass
class GapResult:
    gaps: list = field(default_factory=list)          # list[GapNode] (disagreements)
    corroborations: list = field(default_factory=list)  # list[dict] (agreeing clusters)
    n_claims: int = 0
    n_clusters: int = 0


def detect_controversy(question: str, findings_hits: list) -> list:
    """Topic-level controversy detector (Flag B real fix, H7).

    The pair-wise stance step only fires when two atomic claims LEXICALLY contradict —
    but real findings are usually neutral data points ("Study A found 50% risk", "Study
    B found no effect") that reveal a disagreement only when read TOGETHER. This reads a
    topic's findings as a set and asks: do credible INDEPENDENT sources genuinely disagree
    on the same sub-question? It compares the sources to each other (NOT the model grading
    itself — on-spine, same principle as the pair-wise stance judge). Returns
    [{"point": str, "finding_ids": [id,...]}], each with >=2 findings on opposing sides.
    """
    items = [(str(h.get("id", "")), (h.get("text") or "").strip())
             for h in findings_hits if (h.get("text") or "").strip()]
    if len(items) < 2:
        return []
    listing = "\n".join(f"[{i}] {t[:220]}" for i, (fid, t) in enumerate(items))
    prompt = (
        "Below are findings from INDEPENDENT sources on one question. Flag ONLY places where "
        "two or more of these findings DIRECTLY CONTRADICT each other — one asserts something "
        "another explicitly denies, or they report opposite results on the SAME specific "
        "measure. STRICT rules:\n"
        "- Do NOT flag a claim just because the broader topic is debated or politically charged.\n"
        "- Do NOT flag findings that merely emphasize different factors, scopes, or nuances.\n"
        "- Do NOT flag a mainstream recommendation just because a fringe view exists elsewhere — "
        "the CONTRADICTION must be present IN THE FINDINGS listed below.\n"
        "- BOTH sides must have CREDIBLE backing (real studies/experts/data). Do NOT flag a "
        "well-supported consensus as 'contested' just because ONE lone or fringe finding objects "
        "to it — that is a fringe objection, not a genuine controversy.\n"
        "- Each flagged disagreement must cite specific findings on BOTH sides and state what "
        "each side actually claims. When in doubt, do NOT flag.\n"
        f"QUESTION: {question}\n\nFINDINGS:\n{listing}\n\n"
        'Return STRICT JSON {"disagreements":[{"point":"...","side_a":"...","side_b":"...",'
        '"finding_ids":[numbers on opposing sides]}]}. Empty list if nothing here directly '
        "contradicts.")
    data = _cheap_json(prompt)
    out = []
    for d in data.get("disagreements", []):
        if not isinstance(d, dict):
            continue
        ids = [items[i][0] for i in d.get("finding_ids", [])
               if isinstance(i, int) and 0 <= i < len(items) and items[i][0]]
        ids = sorted(set(ids))
        # require the judge to have named opposing sides AND cite >=2 findings — the
        # two-sided justification is what makes it fire only on real contradiction.
        if d.get("point") and d.get("side_a") and d.get("side_b") and len(ids) >= 2:
            out.append({"point": str(d["point"]), "finding_ids": ids})
    return out


def detect(source_responses: list, question: str, *, branch_id: str = "main",
           extra_claims: list | None = None) -> GapResult:
    # 1. extract claims from each OK source
    items: list = []
    for r in source_responses:
        if getattr(r, "ok", False):
            items.extend(extract_claims(r.raw_text, r.source_label,
                                        source_type=getattr(r, "source_type", "llm")))
    # Contested-firing fix (Vera/Noor flag): the recon voices mostly AGREE on
    # mainstream facts — the genuinely CONTESTED material lives in the retrieved
    # findings (web/social/youtube). Feed those in as first-class claims so a
    # peer-reviewed finding and a contradicting social finding on the same topic
    # can cluster and be judged 'contradict' -> Controversial. Each carries its
    # own distinct source_label, so a real cross-source disagreement is required
    # (never one source contesting itself).
    if extra_claims:
        items.extend(extra_claims)
    if not items:
        return GapResult()

    # 2. embed + cluster (mechanical)
    vecs = _embed([it.text for it in items])
    clusters = _cluster(items, vecs)

    result = GapResult(n_claims=len(items), n_clusters=len(clusters))
    # 3. per multi-source cluster, classify stance
    for members in clusters:
        cl = [items[i] for i in members]
        sources = {c.source_label for c in cl}
        if len(sources) < 2:
            continue  # single-source cluster: not yet contested
        rel = _stance(cl)
        if rel in ("contradict", "mixed"):
            topic = cl[0].text
            score = round(len(sources) / len({c.source_label for c in items}), 3)
            result.gaps.append(GapNode(
                question=f"Sources disagree on: {topic}",
                gap_type="disagreement",
                involved_source_ids=sorted(sources),
                disagreement_score=score,
                branch_id=branch_id))
        else:
            # carry each agreeing source's TYPE so promotion can discount the
            # correlated LLM bloc (Ghost/Elara): N LLMs sharing training data is
            # not N independent confirmations.
            types = sorted({(c.source_label, c.source_type) for c in cl})
            result.corroborations.append(
                {"topic": cl[0].text, "sources": sorted(sources), "n": len(cl),
                 "source_types": [t for _, t in types]})
    return result
