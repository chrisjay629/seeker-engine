"""Confidence-tier promotion (brief 03 — the Memory Map owns finding tiers).

Findings enter the map as "Speculative" (one source, unverified) and, until now,
never moved. This module moves a finding UP the tier ladder when INDEPENDENT
external sources corroborate its claim, and marks it "Controversial" when
independent sources contest it.

Spine (v11): the tier is a deterministic function of HOW MUCH independent
external evidence agrees or disagrees — never a model rating its own confidence.
The corroboration / disagreement clusters come from the Gap Detector, whose
stance step compares sources to EACH OTHER (NLI-style), never self-grades.

Independence weighting (Ghost/Elara, council review 2026-07-06): promotion does
NOT count raw source labels. The recon LLM voices share training data, so N of
them agreeing is one CORRELATED signal, not N independent confirmations — a
shared falsehood would otherwise launder straight to "Accepted" (PoisonedRAG
surface). `independent_evidence()` collapses the LLM bloc to a single vote and
counts genuinely independent sources fully. And tiers are labelled honestly
(TIER_MEANING): "Accepted" = widely corroborated, NOT verified true.

Known limit (rides the Zara refactor): the strongest independence signal —
distinct real-world web DOMAINS from hunt citations — is not yet in the
corroboration clusters (those run on recon voices, a separate subsystem from the
hunt findings). Weighting by distinct domains lands when the Gap Detector is
refactored to cluster findings-with-ids instead of re-extracted claims.

Movement rules, so tiers only ever move toward stronger evidence within a run:
  - promotion is monotonic UP — a later, thinner cycle can't undo a stronger one;
  - a disagreement overrides to "Controversial" — honest instability outranks a
    corroboration count, and a contested finding is never quietly re-promoted.

Matching: a corroboration/disagreement cluster carries claim TEXT, not finding
ids, so we semantically match the cluster topic back to findings already on the
map (cosine via Pinecone) and only touch hits at/above `sim_threshold` — the
same claim, not merely a related one.

Threshold calibration (live-checked 2026-07-06): the Memory Map's Pinecone index
uses llama-text-embed-v2 with ASYMMETRIC embeddings — upsert_records embeds text
as a "passage", search embeds as a "query", so even IDENTICAL text self-matches
at only ~0.65, not 1.0. The default `sim_threshold` is therefore 0.55 (the same
"same-meaning" bar the Gap Detector clusters at), NOT a naive 0.8+. Raising it
above ~0.65 would silently reject exact-claim matches and promote nothing.
"""
from __future__ import annotations

# Ordered confidence ladder (higher = more corroborated). "Controversial" is NOT
# a rung — it is an override applied when sources disagree, so it is kept out of
# the rank map and handled explicitly below.
CONFIDENCE_RANK = {"Speculative": 0, "Moderately Accepted": 1, "Accepted": 2}
CONTESTED = "Controversial"
DISPROVEN = "Disproven"


# Honest tier semantics (Ghost/Elara): a tier reports EVIDENCE WEIGHT, never
# truth. "Accepted" means widely corroborated across independent sources — NOT
# verified true. Consensus can be correlated error; promotion measures agreement.
TIER_MEANING = {
    "Accepted": "widely corroborated across independent sources (not verified true)",
    "Moderately Accepted": "corroborated by more than one independent source",
    "Controversial": "independent sources contest this",
    "Speculative": "single source / not independently corroborated",
    "Disproven": "directly contradicted by cited credible evidence",
}


# --- Part-1 standing standard: "closest to verifiable truth," not absolute fact ---
# (Gambit, 2026-07-11.) Every claim is labelled by its EVIDENTIARY WEIGHT, never a
# binary true/false. The four public-facing labels below are the canonical vocabulary
# Seeker uses in investigations and published articles; they map onto the internal
# tiers this module already computes deterministically from external evidence. The
# doc `Seeker-Vault/00-Blueprint/seeker-epistemic-standard.md` is the human statement.
#
# "Disproven" is the one genuinely new label and it has a HIGH bar: it is set ONLY on
# direct, citation-backed contradiction (via the verify path), never on mere absence
# of support and never on plain disagreement (that stays "Controversial"). Until the
# refutation-detector is wired into the gap step, Disproven is applied by seeker-verify
# when it finds cited disproof — it is never auto-inferred from a low source count.
STANDARD_LABEL = {
    "Accepted": "well-supported",
    "Moderately Accepted": "well-supported",
    "Controversial": "contested",
    "Speculative": "unverified",
    "Disproven": "disproven",
}


def standard_label(tier: str) -> str:
    """Map an internal confidence tier to the public four-label standard vocabulary
    (well-supported / contested / unverified / disproven). Unknown tiers -> unverified."""
    return STANDARD_LABEL.get(tier, "unverified")


def independent_evidence(source_types) -> int:
    """Collapse correlated sources to honest independent-evidence weight.

    Ghost/Elara: the recon LLM voices (Claude/GPT/Gemini/...) share training
    data, so N of them agreeing is ONE correlated signal, not N confirmations.
    The whole LLM bloc therefore counts as a single vote; each genuinely
    independent source (perplexity's grounded search, a youtube practitioner, a
    distinct web domain) counts fully. This is why "5 LLMs agree" can NOT reach
    Accepted on its own.
    """
    types = list(source_types or [])
    has_llm = any(t == "llm" for t in types)
    n_independent = sum(1 for t in types if t != "llm")
    return (1 if has_llm else 0) + n_independent


# Triangulation (Hunt upgrade H5). Independent source-type FAMILIES: the correlated LLM
# bloc collapses to one family; each other retrieval medium is its own independent family.
# A claim confirmed across >=2 families is genuinely cross-verified; one confined to a
# single family (e.g. 3 web blogs) is an echo-chamber risk, not the same strength.
_TYPE_FAMILY = {"llm": "model", "perplexity": "grounded-search",
                "youtube": "practitioner-video", "podcast": "practitioner-audio",
                "structured_source": "primary/authoritative", "primary_source": "primary/authoritative",
                "abstract": "primary/authoritative", "secondary_review": "primary/authoritative",
                "web": "web"}


def triangulation_types(source_types) -> set:
    """Distinct independent source-type families behind a claim (LLM bloc counts once)."""
    return {_TYPE_FAMILY.get(t, "web") for t in (source_types or [])}


def is_triangulated(source_types, min_types: int = 2) -> bool:
    """True when a claim is confirmed across >= min_types DISTINCT independent source
    families — cross-verified, not echoed within one type. If source_types is unknown
    (None), assume triangulated so we never DEMOTE on missing data (fail-open)."""
    if source_types is None:
        return True
    return len(triangulation_types(source_types)) >= min_types


def tier_for_source_count(evidence: int) -> str:
    """External math only: independent-evidence weight -> tier."""
    if evidence >= 3:
        return "Accepted"
    if evidence == 2:
        return "Moderately Accepted"
    return "Speculative"


def promote_from_gap_result(mm, gap_result, *, branch_id: str = "main",
                            sim_threshold: float = 0.55, top_k: int = 3) -> dict:
    """Apply corroboration promotions and disagreement contests to the map.

    Returns {"promoted": [...], "contested": [...]} for the run trail. Every
    entry records the finding id, old/new tier, and the external evidence
    (n_sources / the sources) that moved it — proof-of-work, not opinion.
    """
    promoted: list = []
    contested: list = []

    # 1. corroboration -> promote the ONE best-matching finding UP.
    # A cluster is about a single claim, so we move only its nearest finding, not
    # every semantically-adjacent neighbour (at this index's scale, related-but-
    # different findings still clear a loose threshold — best-match keeps it 1:1).
    for corr in getattr(gap_result, "corroborations", []):
        # independence-weighted evidence, not raw source count (Ghost/Elara).
        # Fall back to raw count only if a producer didn't tag source_types.
        source_types = corr.get("source_types")
        evidence = (independent_evidence(source_types) if source_types is not None
                    else len(corr.get("sources", [])))
        target = tier_for_source_count(evidence)
        # Triangulation gate (H5): the top tier must be cross-verified across >=2 distinct
        # independent source TYPES — 3 echoes of one type (e.g. 3 web blogs) is not
        # "Accepted", it's "Moderately Accepted". Fail-open when types are unknown.
        triangulated = is_triangulated(source_types)
        if target == "Accepted" and not triangulated:
            target = "Moderately Accepted"
        if CONFIDENCE_RANK[target] == 0:
            continue  # correlated echo or single source: corroborates nothing
        best = _best_match(mm, corr["topic"], branch_id, top_k, sim_threshold)
        if best is None:
            continue
        cur = best.get("confidence_tier", "Speculative")
        if cur == CONTESTED:
            continue  # contested findings are not quietly re-promoted
        if CONFIDENCE_RANK[target] > CONFIDENCE_RANK.get(cur, 0):
            mm.set_tier(best["id"], target, branch_id=branch_id)
            promoted.append({"id": best["id"], "from": cur, "to": target,
                             "evidence": evidence, "n_sources": len(corr.get("sources", [])),
                             "sources": corr.get("sources", []),
                             "source_types": source_types, "triangulated": triangulated,
                             "match": round(best["score"], 3)})

    # 2. disagreement -> mark the ONE best-matching finding Controversial (override)
    for gap in getattr(gap_result, "gaps", []):
        topic = getattr(gap, "question", "").replace("Sources disagree on: ", "")
        if not topic:
            continue
        best = _best_match(mm, topic, branch_id, top_k, sim_threshold)
        if best is None:
            continue
        cur = best.get("confidence_tier", "Speculative")
        if cur == CONTESTED:
            continue
        mm.set_tier(best["id"], CONTESTED, branch_id=branch_id)
        contested.append({"id": best["id"], "from": cur, "to": CONTESTED,
                          "sources": getattr(gap, "involved_source_ids", []),
                          "match": round(best["score"], 3)})

    return {"promoted": promoted, "contested": contested}


def _best_match(mm, text: str, branch_id: str, top_k: int, floor: float):
    """Nearest finding to `text` on the map, or None if none clears `floor`.

    NOTE (live-checked): this index's `search` does NOT reliably return hits in
    score order — the true nearest can come back last. So pick the max by score
    explicitly; never trust position 0."""
    hits = mm.query(text, branch_id=branch_id, top_k=top_k, node_kind="finding")
    if not hits:
        return None
    best = max(hits, key=lambda h: h["score"])
    return best if best["score"] >= floor else None
