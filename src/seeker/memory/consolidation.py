"""Consolidation on ingest (brief 03) — stop the firehose at the source.

Before a finding is added, if it's a near-duplicate of an existing node AND not
contradictory, MERGE instead of adding a copy: union the sources/urls (preserve
provenance — Ghost), bump the corroboration count, and raise the confidence tier
from that EXTERNAL count (Zara — the merge count IS the tier signal). One feature
fixes bloat and powers the tiers.

Spine (Vera): the similarity decision is mechanical (cosine >= threshold,
calibrated to this embedder). The only model call is an EXTERNAL contradiction
check comparing the NEW claim to the EXISTING one (Noor: never silently merge a
disagreement into agreement) — it compares two independent claims, never self-
grades. Fails safe: on a gate error it does NOT merge (keeps them separate).

Calibration (audit-verified): llama-text-embed-v2 passage cosine ~1.0 for
verbatim, ~0.60 for a redundant paraphrase. MERGE threshold = 0.60.
"""
from __future__ import annotations

import json

import requests

from .. import config
from ..models import Finding
from .confidence import tier_for_source_count

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Pinecone's SDK uses its own urllib3 client with NO socket timeout, so a stalled embed call hangs
# forever — outside our requests-layer guards entirely (a run once froze 10 min here; the watchdog
# aborted it). We run every embed on a never-joined worker pool with a HARD result-timeout: a hung
# embed becomes a fail-open miss (skip twin-detection for that batch) instead of a frozen run. The
# pool is module-level and never shut down, so a leaked worker can't block interpreter exit.
import concurrent.futures as _cf
_EMBED_TIMEOUT = 60
_EMBED_POOL = _cf.ThreadPoolExecutor(max_workers=3, thread_name_prefix="pc-embed")


def _embed(mm, texts: list) -> list:
    """Pinecone passage-embed a batch, hard-bounded at _EMBED_TIMEOUT. Returns list-of-vectors, or []
    on timeout/error (caller treats an empty result as 'no twin info' — fail-open, never a hang)."""
    def _call():
        # Jina, not Pinecone inference (2026-07-28): the integrated path is metered and its 5M
        # monthly quota is exhausted. Must use the SAME model/space as memory_map._embed or twin
        # similarity scores become meaningless against the stored vectors.
        from .memory_map import _embed as _map_embed
        return _map_embed(texts)
    try:
        return _EMBED_POOL.submit(_call).result(timeout=_EMBED_TIMEOUT)
    except Exception:
        return []


MERGE_THRESHOLD = 0.60
VERBATIM_THRESHOLD = 0.90
# Collaborative duplicates (same conclusion, DIFFERENT wording/source) share
# meaning but not vocabulary, so they score LOWER than paraphrases — measured
# ~0.52 for a genuine cross-source corroboration. Nesting therefore casts a wider
# net than merging: [NEST_FLOOR, MERGE_THRESHOLD) is the "classify, nest only if
# collaborative, never merge" band. Below NEST_FLOOR = noise, skip (cost control).
NEST_FLOOR = 0.45


def _contradicts(a: str, b: str) -> bool:
    """External check: do these two independent claims contradict on substance?
    Fails SAFE (returns True on error) so an outage never merges a disagreement."""
    prompt = (
        "Do these two claims CONTRADICT each other on substance (a real conflict "
        "in fact/number/direction), or are they the same claim reworded / "
        "compatible? Return STRICT JSON {\"contradicts\": true/false}.\n\n"
        f"A: {a}\nB: {b}")
    try:
        r = requests.post(
            _OPENROUTER_URL,
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.EXTRACTOR_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"}},
            timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        return bool(json.loads(r.json()["choices"][0]["message"]["content"]).get("contradicts"))
    except Exception:
        return True   # fail safe: don't merge if we can't verify non-contradiction


def classify_relation(a: str, b: str) -> str:
    """External THREE-STATE classifier (Proposal 2). Cosine only tells us two
    claims are *near* in vector space — it cannot tell agreement from a distinct
    fact on the same topic (the 5-min vs 1-hour cache-price pair scored 0.889 yet
    are different facts). So an outside semantic pass decides the relation:

      "same"          -> identical claim reworded; FULL merge (wording is redundant)
      "collaborative" -> SAME core conclusion, different source/angle/wording; NEST
                         (keep both wordings; corroboration is signal, not noise)
      "distinct"      -> different fact/number/scope even if same topic; keep SEPARATE
      "contradicts"   -> real conflict in fact/number/direction; keep SEPARATE (contested)

    Fails SAFE to "distinct" (keep separate) so an outage never merges or nests
    incorrectly — the only harmful errors are false-merge and false-nest."""
    prompt = (
        "Classify the RELATION between two research findings. Return STRICT JSON "
        "{\"relation\": \"same\"|\"collaborative\"|\"distinct\"|\"contradicts\"}.\n"
        "- same: the identical claim reworded (same fact, same numbers).\n"
        "- collaborative: they reach the SAME core conclusion but from a different "
        "source, angle, or wording (independent corroboration).\n"
        "- distinct: related topic but a DIFFERENT fact, number, or scope "
        "(e.g. 5-minute vs 1-hour pricing are DISTINCT, not same).\n"
        "- contradicts: a real conflict in fact, number, or direction.\n\n"
        f"A: {a}\nB: {b}")
    try:
        r = requests.post(
            _OPENROUTER_URL,
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.EXTRACTOR_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"}},
            timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        rel = json.loads(r.json()["choices"][0]["message"]["content"]).get("relation")
        return rel if rel in ("same", "collaborative", "distinct", "contradicts") else "distinct"
    except Exception:
        return "distinct"   # fail safe: keep separate, never wrongly merge/nest


def upsert_consolidated(mm, f: Finding, *, threshold: float = MERGE_THRESHOLD,
                        check_contradiction: bool = True, nest: bool = True,
                        vector: list | None = None) -> dict:
    """Add `f` with THREE-STATE consolidation. If a near-neighbour exists (cosine
    >= threshold), an external classifier decides merge / nest / separate.
    Returns {"action": "new"|"merged"|"nested"|"kept_contested", ...}."""
    # `vector`, when the caller already embedded this claim, removes BOTH remaining round-trips
    # for this finding (the neighbour query and the upsert). The batch path always has it.
    hits = mm.query(f.claim, branch_id=f.branch_id, top_k=1, node_kind="finding", vector=vector)
    best = hits[0] if hits else None
    nearest = float(best["score"]) if best else 0.0   # read-only novelty signal

    if best and best["score"] >= threshold:
        # near-verbatim shortcut: no LLM needed, it's the same claim
        if best["score"] >= VERBATIM_THRESHOLD:
            rel = "same"
        elif check_contradiction:
            rel = classify_relation(f.claim, best["text"])
        else:
            rel = "same"

        if rel == "same":
            meta = mm.get_meta(best["id"], branch_id=f.branch_id)
            new_count = int(meta.get("corroboration_count", 1)) + 1
            res = mm.merge_into(best["id"], f, tier_for_source_count(new_count),
                                branch_id=f.branch_id)
            res.update({"action": "merged", "score": best["score"]})
            return res
        if rel == "collaborative" and nest:
            res = mm.nest_into(best["id"], f, branch_id=f.branch_id)
            res["score"] = best["score"]
            return res
        if rel == "contradicts":
            mm.upsert_finding(f, vector=vector)
            return {"action": "kept_contested", "id": f.id, "near": best["id"],
                    "score": best["score"]}
        # rel == "distinct" (or nest disabled) -> fall through to a new node

    elif best and nest and check_contradiction and best["score"] >= NEST_FLOOR:
        # wider band: too far to be a paraphrase, close enough to possibly be a
        # cross-source corroboration. Only NEST here (never merge below threshold).
        rel = classify_relation(f.claim, best["text"])
        if rel == "collaborative":
            res = mm.nest_into(best["id"], f, branch_id=f.branch_id)
            res["score"] = best["score"]
            return res
        if rel == "contradicts":
            mm.upsert_finding(f, vector=vector)
            return {"action": "kept_contested", "id": f.id, "near": best["id"],
                    "score": best["score"]}
        # same/distinct at this distance -> keep separate (conservative)

    mm.upsert_finding(f, vector=vector)   # distinct — new node, corroboration_count = 1
    return {"action": "new", "id": f.id, "nearest_score": nearest}


def dedupe_existing_verbatim(mm, *, branch_id: str = "main",
                             threshold: float = VERBATIM_THRESHOLD,
                             dry_run: bool = True) -> dict:
    """One-off cleanup of the EXISTING map: find near-VERBATIM clusters (cosine
    >= threshold, default 0.90 = true duplicates, not paraphrases) and fold each
    cluster into one keeper — union provenance, bump corroboration, delete the
    extras. dry_run=True only reports. Safe: only near-verbatim, provenance
    merged into the keeper BEFORE any delete."""
    import numpy as np
    from ..memory.memory_map import TEXT_FIELD

    all_ids = []
    for page in mm._index.list(namespace=branch_id):
        all_ids.extend(page if isinstance(page, (list, tuple)) else [page])
    id2text = {}
    for i in range(0, len(all_ids), 100):
        rec = mm._index.fetch(ids=all_ids[i:i + 100], namespace=branch_id)
        vectors = getattr(rec, "vectors", None) or (
            rec.get("vectors", {}) if isinstance(rec, dict) else {})
        for nid, v in vectors.items():
            meta = getattr(v, "metadata", None) or getattr(v, "fields", None) or {}
            id2text[nid] = (meta.get(TEXT_FIELD, "") if isinstance(meta, dict)
                            else getattr(meta, TEXT_FIELD, "")) or ""
    ids = list(id2text.keys())
    texts = [id2text[i] for i in ids]

    # embed + cosine
    vecs = []
    for i in range(0, len(texts), 90):
        batch = _embed(mm, texts[i:i + 90])
        if not batch:
            return []            # embed failed/timed out — skip twin detection this pass (fail-open)
        vecs.extend(batch)
    M = np.asarray(vecs, dtype=np.float32)
    Mn = M / np.clip(np.linalg.norm(M, axis=1, keepdims=True), 1e-9, None)
    sim = Mn @ Mn.T
    np.fill_diagonal(sim, -1.0)

    # union-find over pairs >= threshold
    parent = list(range(len(ids)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    iu = np.triu_indices(len(ids), 1)
    for k in np.where(sim[iu] >= threshold)[0]:
        a, b = int(iu[0][k]), int(iu[1][k])
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    clusters = {}
    for i in range(len(ids)):
        clusters.setdefault(find(i), []).append(i)
    dup_clusters = [c for c in clusters.values() if len(c) > 1]

    merged, deleted = 0, 0
    examples = []
    for c in dup_clusters:
        keeper = c[0]
        if len(examples) < 6:
            examples.append(texts[keeper][:80])
        if dry_run:
            continue
        for other in c[1:]:
            # merge provenance into keeper BEFORE deleting the duplicate
            meta_k = mm.get_meta(ids[keeper], branch_id=branch_id)
            meta_o = mm.get_meta(ids[other], branch_id=branch_id)
            cnt = int(meta_k.get("corroboration_count", 1)) + int(meta_o.get("corroboration_count", 1))
            urls = sorted({u for u in (meta_k.get("urls", []) + meta_o.get("urls", [])) if u and u != "_"}) or ["_"]
            sids = sorted({s for s in (meta_k.get("source_ids", []) + meta_o.get("source_ids", [])) if s and s != "_"}) or ["_"]
            mm._index.update(id=ids[keeper], namespace=branch_id,
                             set_metadata={"corroboration_count": cnt, "urls": urls,
                                           "source_ids": sids,
                                           "confidence_tier": tier_for_source_count(cnt)})
            mm.delete_node(ids[other], branch_id=branch_id)
            merged += 1
            deleted += 1

    return {"dup_clusters": len(dup_clusters), "would_remove": sum(len(c) - 1 for c in dup_clusters),
            "removed": deleted, "dry_run": dry_run, "examples": examples,
            "total_nodes": len(ids)}


def _embed_passages(mm, texts: list) -> list:
    """Passage embeddings for in-batch twin detection (same model/space the map
    uses). Batched to respect the inference payload limit."""
    vecs = []
    for i in range(0, len(texts), 90):
        batch = _embed(mm, texts[i:i + 90])
        if not batch:
            return []            # embed failed/timed out — fail-open (caller handles empty)
        vecs.extend(batch)
    return vecs


def upsert_findings_consolidated(mm, findings: list, *,
                                 check_contradiction: bool = True,
                                 threshold: float = MERGE_THRESHOLD) -> dict:
    """Batch consolidate. Returns a summary so the firehose control is VISIBLE
    (Luna): how many were new vs merged vs kept-as-contested.

    Closes the index-lag gap (Cipher/Vera): Pinecone upserts aren't queryable
    immediately, so same-batch paraphrases can't see each other via mm.query and
    each becomes its own node. We keep an IN-MEMORY buffer of this batch's just-
    added nodes and check every new finding against it FIRST — catching twins the
    index can't yet return. THREE-STATE (Proposal 2): a same-batch collision is
    classified same / collaborative / distinct; same -> merge, collaborative ->
    nest (keep both wordings), distinct/contradicts -> fall through. Same spine:
    cosine gates, an EXTERNAL classifier decides; merge/nest bump corroboration."""
    import numpy as np
    from .novelty import tier as novelty_tier, empty_tally

    summary = {"new": 0, "merged": 0, "nested": 0, "kept_contested": 0,
               "in": len(findings), "novelty": empty_tally()}
    if not findings:
        summary["distinct_added"] = 0
        return summary

    vecs = _embed_passages(mm, [f.claim for f in findings])
    buf = []   # this batch's distinct nodes: {"vecn": unit vec, "id", "claim"}
    from .. import watchdog
    for f, v in zip(findings, vecs):
        watchdog.beat("consolidating")   # each finding processed = progress; resets the stall clock
        vn = np.asarray(v, dtype=np.float32)
        vn = vn / max(float(np.linalg.norm(vn)), 1e-9)

        # 1) same-batch twin? (the collision mm.query can't see yet)
        twin, best = None, 0.0
        for b in buf:
            s = float(vn @ b["vecn"])
            if s > best:
                best, twin = s, b
        if twin and best >= threshold:
            rel = "same" if best >= VERBATIM_THRESHOLD else (
                classify_relation(f.claim, twin["claim"]) if check_contradiction
                else "same")
            if rel == "same":
                meta = mm.get_meta(twin["id"], branch_id=f.branch_id)
                new_count = int(meta.get("corroboration_count", 1)) + 1
                mm.merge_into(twin["id"], f, tier_for_source_count(new_count),
                              branch_id=f.branch_id)
                summary["merged"] += 1
                summary["novelty"][novelty_tier(best)] += 1
                continue
            if rel == "collaborative":
                mm.nest_into(twin["id"], f, branch_id=f.branch_id)
                summary["nested"] += 1
                summary["novelty"][novelty_tier(best)] += 1
                continue
            # distinct / contradicts vs the twin -> fall through to cross-map
        elif twin and best >= NEST_FLOOR and check_contradiction:
            # wider band: possible cross-source corroboration — nest only
            if classify_relation(f.claim, twin["claim"]) == "collaborative":
                mm.nest_into(twin["id"], f, branch_id=f.branch_id)
                summary["nested"] += 1
                summary["novelty"][novelty_tier(best)] += 1
                continue

        # 2) otherwise the normal cross-map consolidation (against indexed nodes)
        r = upsert_consolidated(mm, f, threshold=threshold,
                                check_contradiction=check_contradiction, vector=v)
        summary[r["action"]] += 1
        summary["novelty"][novelty_tier(r.get("nearest_score", r.get("score", 0.0)))] += 1
        if r["action"] in ("new", "kept_contested"):
            buf.append({"vecn": vn, "id": f.id, "claim": f.claim})

    summary["distinct_added"] = summary["new"] + summary["kept_contested"]
    return summary
