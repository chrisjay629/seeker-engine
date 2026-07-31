"""Memory Map — spatial coordinate index (brief 03).

Seeker's external memory. It does NOT think — it files, embeds, retrieves.
Backed by Pinecone with integrated inference (llama-text-embed-v2, 1024-dim,
cosine): Pinecone embeds text on upsert, so there is no separate embedding API.

Isolation (Marcus): branch_id maps to a Pinecone namespace, so an introspective
branch is structurally walled off from the main investigation's nodes.
"""
from __future__ import annotations

import json
import time
from typing import Optional

from pinecone import Pinecone

from .. import config
from ..models import Finding, GapNode

INDEX_NAME = "seeker-memory-map"
TEXT_FIELD = "chunk_text"   # matches the index field_map
EMBED_DIM = 1024            # llama-text-embed-v2 and jina-embeddings-v3 are both 1024-d


# EMBED CACHE (2026-07-28). v17 measured 2h41m against v15's pre-migration 59m; batching the WRITE
# path recovered only ~3% because the real cost moved to READS: every mm.query() now costs a Jina hop
# PLUS a Pinecone hop, where integrated inference did both in one call. And the same strings are
# embedded over and over in a run — the subject line is re-queried by synthesis, entity_profiles,
# evidence_for, connections and discovery, dozens of times.
#
# Keyed on (task, text) — NOT text alone (Cipher): jina v3 returns DIFFERENT vectors for
# retrieval.query vs retrieval.passage, so a text-only key would hand a passage vector to a query and
# silently degrade every search. Bounded so a long run cannot balloon memory (Noor); exact-text keys
# mean a cached vector can never be stale for its input.
_EMBED_CACHE: dict = {}
_EMBED_CACHE_MAX = 4000
_EMBED_STATS = {"calls": 0, "hits": 0, "embedded": 0}


def embed_stats() -> dict:
    """Cache effectiveness for the run — so the next perf claim is measured, not asserted (Vera)."""
    s = dict(_EMBED_STATS)
    s["hit_rate"] = round(s["hits"] / max(1, s["calls"]), 3)
    return s


def _embed(texts: list, *, query: bool = False) -> list:
    """Embed text OURSELVES via Jina, instead of letting Pinecone do it.

    WHY (2026-07-28): Pinecone's integrated inference (upsert_records / search with `inputs`)
    embeds server-side and meters it — and the free tier's 5,000,000 monthly embedding tokens ran
    out mid-v16 after ~16 runs, which blocked BOTH writes AND reads. The dashboard showed the rest
    of the index barely touched: RUs 78K/1M, storage 0.13/2GB, WUs 350K/2M. Only the embedding
    quota was gone. Embedding elsewhere and upserting raw vectors moves the work onto the resources
    we have 82-93% headroom on, and removes a ceiling we would otherwise keep hitting.

    ONE function for BOTH upsert and query (Zara) — if the two ever used different models the
    vectors would land in different spaces and every search would silently return noise.

    Jina v3 supports task-specific embeddings: passages and queries get different task types, which
    is what asymmetric retrieval wants (a short question should match a longer claim).

    Raises on failure — deliberately NOT fail-open (Noor): silently storing nothing, or querying
    with a zero vector, would corrupt the map invisibly. A loud failure is recoverable; a quiet one
    poisons every downstream organ."""
    rows = [str(x) for x in texts if str(x).strip()]
    if not rows:
        return []
    task = "retrieval.query" if query else "retrieval.passage"
    _EMBED_STATS["calls"] += len(rows)
    cached = {i: _EMBED_CACHE[(task, s)] for i, s in enumerate(rows) if (task, s) in _EMBED_CACHE}
    _EMBED_STATS["hits"] += len(cached)
    todo = [(i, s) for i, s in enumerate(rows) if i not in cached]
    if not todo:                      # everything already known — zero network
        return [cached[i] for i in range(len(rows))]
    import requests
    r = requests.post(
        "https://api.jina.ai/v1/embeddings",
        headers={"Authorization": f"Bearer {config.require('JINA_API_KEY')}",
                 "Content-Type": "application/json"},
        json={"model": "jina-embeddings-v3", "dimensions": EMBED_DIM,
              "task": task, "input": [s for _i, s in todo]},
        timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    vecs = [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d.get("index", 0))]
    if len(vecs) != len(todo):
        raise RuntimeError(f"embedding count mismatch: {len(vecs)} for {len(todo)} inputs")
    _EMBED_STATS["embedded"] += len(vecs)
    for v in vecs:
        # a wrong-dimension vector would be REJECTED by the index or, worse, silently mis-stored;
        # assert here where the error still names the cause (Noor)
        if len(v) != EMBED_DIM:
            raise RuntimeError(f"embedding dim {len(v)} != index dim {EMBED_DIM}")
    for (i, s), v in zip(todo, vecs):
        cached[i] = v
        if len(_EMBED_CACHE) < _EMBED_CACHE_MAX:
            _EMBED_CACHE[(task, s)] = v
    return [cached[i] for i in range(len(rows))]


class MemoryMap:
    def __init__(self, api_key: Optional[str] = None):
        self._pc = Pinecone(api_key=api_key or config.require("PINECONE_API_KEY"))
        self._index = self._pc.Index(INDEX_NAME)

    def wait_ready(self, timeout: int = 120) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            desc = self._pc.describe_index(INDEX_NAME)
            if desc.get("status", {}).get("ready"):
                return True
            time.sleep(3)
        return False

    # --- writes ---
    def upsert_finding(self, f: Finding, corroboration_count: int = 1,
                       vector: Optional[list] = None) -> None:
        """Store a finding as a lit node. `corroboration_count` = how many
        independent sources have asserted this claim (1 on first ingest; the
        consolidator bumps it on merge, feeding the confidence tier)."""
        rec = {
            "_id": f.id,
            TEXT_FIELD: f.claim,
            "node_kind": "finding",
            "status": "lit",
            "confidence_tier": f.confidence_tier,
            "source_ids": list(f.source_ids) or ["_"],
            "urls": [c.url for c in f.citations if getattr(c, "url", "")] or ["_"],
            # which ORGAN produced this (web/youtube/podcast/primary/structured_source/...) —
            # persisted so the organ mix is recoverable post-run for honest dashboards (#15d)
            "source_types": sorted({getattr(c, "source_type", "web") or "web"
                                    for c in f.citations}) or ["web"],
            "corroboration_count": corroboration_count,
            "created_at": f.created_at,
        }
        # self-embedded upsert (2026-07-28): the integrated-inference path (upsert_records) is what
        # exhausted the 5M/month embedding quota. Same metadata, we just supply the vector.
        #
        # REUSE A CALLER'S VECTOR (2026-07-28, perf): the consolidator ALREADY batch-embeds every
        # claim to do twin detection, and then this method re-embedded the identical text one call
        # at a time — every finding embedded TWICE, the second time serially. That is what turned a
        # 59-minute run into 2h46m. When the caller passes the vector it already computed, this
        # costs zero extra round-trips. Same model, same space (it came from _embed).
        vec = list(vector) if vector else _embed([f.claim])[0]
        if len(vec) != EMBED_DIM:
            raise RuntimeError(f"supplied vector dim {len(vec)} != index dim {EMBED_DIM}")
        meta = {k: v for k, v in rec.items() if k != "_id"}
        self._index.upsert(namespace=f.branch_id, vectors=[{"id": f.id, "values": vec,
                                                            "metadata": meta}])

    def get_meta(self, node_id: str, *, branch_id: str = "main") -> dict:
        """Fetch a node's full stored metadata (for the consolidator's merge)."""
        rec = self._index.fetch(ids=[node_id], namespace=branch_id)
        vectors = getattr(rec, "vectors", None) or (
            rec.get("vectors", {}) if isinstance(rec, dict) else {})
        v = vectors.get(node_id)
        if v is None:
            return {}
        meta = getattr(v, "metadata", None) or getattr(v, "fields", None) or {}
        return dict(meta) if not isinstance(meta, dict) else meta

    def get_metas(self, node_ids: list, *, branch_id: str = "main") -> dict:
        """Batch fetch-by-id -> {id: metadata}. One call, and STRONGLY consistent (unlike
        `query`, which is eventually consistent) — so a tier just written by set_tier is
        reflected immediately. Fails soft to {} so a fetch outage never breaks the caller."""
        ids = [i for i in dict.fromkeys(node_ids) if i]
        if not ids:
            return {}
        try:
            rec = self._index.fetch(ids=ids, namespace=branch_id)
        except Exception:
            return {}
        vectors = getattr(rec, "vectors", None) or (
            rec.get("vectors", {}) if isinstance(rec, dict) else {})
        out = {}
        for nid, v in (vectors or {}).items():
            meta = getattr(v, "metadata", None) or getattr(v, "fields", None) or {}
            out[nid] = dict(meta) if not isinstance(meta, dict) else meta
        return out

    def merge_into(self, existing_id: str, new: Finding, new_tier: str,
                   *, branch_id: str = "main") -> dict:
        """Fold a near-duplicate finding INTO an existing node: union the source
        ids + urls (preserve every source's provenance — Ghost), bump the
        corroboration count, set the tier. Never re-embeds; keeps the vector."""
        meta = self.get_meta(existing_id, branch_id=branch_id)
        prior_ids = [s for s in meta.get("source_ids", []) if s and s != "_"]
        prior_urls = [u for u in meta.get("urls", []) if u and u != "_"]
        new_ids = [s for s in new.source_ids if s]
        new_urls = [c.url for c in new.citations if getattr(c, "url", "")]
        prior_types = [t for t in meta.get("source_types", []) if t and t != "_"]
        new_types = [getattr(c, "source_type", "web") or "web" for c in new.citations]
        count = int(meta.get("corroboration_count", 1)) + 1
        self._index.update(
            id=existing_id, namespace=branch_id,
            set_metadata={
                "source_ids": sorted(set(prior_ids + new_ids)) or ["_"],
                "urls": sorted(set(prior_urls + new_urls)) or ["_"],
                "source_types": sorted(set(prior_types + new_types)) or ["web"],
                "corroboration_count": count,
                "confidence_tier": new_tier,
            })
        return {"into": existing_id, "corroboration_count": count, "tier": new_tier}

    def nest_into(self, parent_id: str, new: Finding, *,
                  branch_id: str = "main") -> dict:
        """Fold a COLLABORATIVE duplicate into an existing node WITHOUT destroying
        its wording (Proposal 2). Unlike merge_into — which unions provenance but
        discards the child's claim text — nesting keeps each child's original
        claim/source/url as a linked sub-finding under one parent node. The map
        stays lean (still ONE node) while the corroboration signal (N independent
        sources reaching the same conclusion, in their own words) is preserved and
        made visible. Children are stored as JSON strings (Pinecone allows a list
        of strings); the corroboration count = number of nested children."""
        from .confidence import tier_for_source_count

        meta = self.get_meta(parent_id, branch_id=branch_id)
        children = list(meta.get("children", []))
        if not children:                      # first nest: seed parent's own claim
            children.append(json.dumps({
                "claim": meta.get(TEXT_FIELD, ""),
                "source_ids": [s for s in meta.get("source_ids", []) if s and s != "_"],
                "urls": [u for u in meta.get("urls", []) if u and u != "_"]}))
        children.append(json.dumps({
            "claim": new.claim,
            "source_ids": [s for s in new.source_ids if s],
            "urls": [c.url for c in new.citations if getattr(c, "url", "")]}))

        prior_ids = [s for s in meta.get("source_ids", []) if s and s != "_"]
        prior_urls = [u for u in meta.get("urls", []) if u and u != "_"]
        new_ids = [s for s in new.source_ids if s]
        new_urls = [c.url for c in new.citations if getattr(c, "url", "")]
        prior_types = [t for t in meta.get("source_types", []) if t and t != "_"]
        new_types = [getattr(c, "source_type", "web") or "web" for c in new.citations]
        count = len(children)                 # one child per corroborating source
        tier = tier_for_source_count(count)
        self._index.update(
            id=parent_id, namespace=branch_id,
            set_metadata={
                "source_ids": sorted(set(prior_ids + new_ids)) or ["_"],
                "urls": sorted(set(prior_urls + new_urls)) or ["_"],
                "source_types": sorted(set(prior_types + new_types)) or ["web"],
                "children": children,
                "nested": True,
                "corroboration_count": count,
                "confidence_tier": tier,
            })
        return {"into": parent_id, "action": "nested", "nested_children": count,
                "corroboration_count": count, "tier": tier}

    def upsert_gap(self, g: GapNode) -> None:
        """Store a gap as a dim node."""
        rec = {
            "_id": g.id,
            TEXT_FIELD: g.question,
            "node_kind": "gap",
            "gap_type": g.gap_type,
            "status": g.status,
            "disagreement_score": g.disagreement_score,
            "involved_source_ids": list(g.involved_source_ids) or ["_"],
            "created_at": g.created_at,
        }
        vec = _embed([rec.get(TEXT_FIELD, "") or g.question])[0]
        meta = {k: v for k, v in rec.items() if k != "_id"}
        self._index.upsert(namespace=g.branch_id, vectors=[{"id": g.id, "values": vec,
                                                            "metadata": meta}])

    def upsert_findings(self, findings: list, branch_id: str = "main") -> int:
        n = 0
        for f in findings:
            self.upsert_finding(f)
            n += 1
        return n

    # --- reads ---
    def query(self, text: str, *, branch_id: str = "main", top_k: int = 5,
              node_kind: Optional[str] = None, tier: Optional[str] = None,
              rerank: bool = False, hybrid: bool = False,
              vector: Optional[list] = None) -> list:
        """Return nearest nodes to `text`. Vector-only by default (cosine).

        hybrid=True (production hybrid retrieval — measured & adopted): fuse the
        vector results with BM25 lexical results via weighted RRF (favoring BM25).
        Fixes exact-term/number lookups vector search misses, without hurting
        semantics (build-log 2026-07-08). Uses a cached per-brain BM25 index; fails
        safe to the vector order on any error. NOTE: kept OFF for the calibrated
        dedup path — only for relevance-driven retrieval (the Mind, search).

        rerank=True: cross-encoder re-order (pinecone-rerank-v0). Measured and NOT
        adopted (didn't help our data) — kept off-by-default for future re-testing."""
        fetch_k = top_k * 4 if (rerank or hybrid) else top_k
        filt = {}
        if node_kind:
            filt["node_kind"] = {"$eq": node_kind}
        if tier:  # restrict to a confidence tier (e.g. surface contested findings directly)
            filt["confidence_tier"] = {"$eq": tier}
        # self-embedded query, same model+space as the upserts (Zara: one _embed for both, or
        # searches silently return noise). task=retrieval.query for asymmetric matching.
        # REUSE a caller's vector when it has one (perf, 2026-07-28). The consolidator compares a
        # claim against other CLAIMS — passage-to-passage — so its batch passage vector is not only
        # free here, it is the more correct embedding for that comparison than re-embedding the
        # claim as a "query".
        qvec = list(vector) if vector else _embed([text], query=True)[0]
        res = self._index.query(namespace=branch_id, vector=qvec, top_k=fetch_k,
                                include_metadata=True, filter=filt or None)
        matches = res.get("matches", []) if isinstance(res, dict) else (getattr(res, "matches", []) or [])
        hits = [{"_id": m.get("id") if isinstance(m, dict) else m.id,
                 "_score": (m.get("score") if isinstance(m, dict) else m.score) or 0,
                 "fields": dict((m.get("metadata") if isinstance(m, dict) else m.metadata) or {})}
                for m in matches]
        out = []
        for h in hits:
            fields = h.get("fields", {})
            stypes = fields.get("source_types", []) or []
            out.append({"id": h.get("_id"), "score": round(h.get("_score", 0), 4),
                        "text": fields.get(TEXT_FIELD, ""),
                        "node_kind": fields.get("node_kind"),
                        "status": fields.get("status"),
                        "confidence_tier": fields.get("confidence_tier",
                                                      "Speculative"),
                        "source_types": stypes,
                        "urls": fields.get("urls", []),
                        "corroboration_count": int(fields.get("corroboration_count", 1) or 1),
                        # cross-source corroboration is the quality signal Chris wants ranked over
                        # popularity: a claim reached by N independent organs is stronger than one
                        # echoed by many low-quality copies of the same source (#15c)
                        "cross_source": len(stypes) > 1})
        if hybrid and len(out) > 1:
            try:
                from .lexical import lexical_index, weighted_rrf
                idx = lexical_index(self, branch_id)
                bm_ids = idx.top(text, top_k * 4, node_kind=node_kind)
                dense_ids = [h["id"] for h in out]
                fused = weighted_rrf([dense_ids, bm_ids], weights=[1.0, 2.0], top=top_k)
                dmap = {h["id"]: h for h in out}
                return [dmap[i] if i in dmap else idx.as_hit(i) for i in fused]
            except Exception:
                return out[:top_k]   # fail safe: vector order

        if rerank and len(out) > 1:
            try:
                docs = [h["text"] for h in out]
                rr = self._pc.inference.rerank(
                    model="pinecone-rerank-v0", query=text, documents=docs,
                    top_n=min(top_k, len(docs)))
                ordered = []
                for item in rr.data:
                    hit = out[item.index]
                    hit["rerank_score"] = round(float(item.score), 4)
                    ordered.append(hit)
                return ordered
            except Exception:
                pass   # fail safe: fall back to vector order
        return out[:top_k]

    def organ_mix(self, text: str, *, branch_id: str = "main", top_k: int = 2000) -> dict:
        """Tally which ORGANS produced a branch's findings -> {source_type: count} (#15d).

        Enables honest dashboards ('web 800 / youtube 68 / podcast 27') instead of 'unknown'.
        A finding with multiple source_types counts once per type. Only findings stored AFTER
        the source_types persistence landed carry the tag; older ones fall back to 'web'."""
        from collections import Counter
        c = Counter()
        for h in self.query(text, branch_id=branch_id, top_k=top_k, node_kind="finding"):
            types = h.get("source_types") or ["web"]
            for st in ([types] if isinstance(types, str) else types):
                c[st or "web"] += 1
        return dict(c)

    def top_corroborated(self, text: str, *, branch_id: str = "main", top_k: int = 15,
                         pool: int = 200) -> list:
        """Rank findings by CORROBORATION, not popularity (#15c, Chris's quality recipe).

        Sort a relevance pool by: cross-organ agreement first (a claim reached by >1 organ type),
        then corroboration_count (independent sources), then similarity. This surfaces the claims
        MULTIPLE independent sources reached — the opposite of ranking by a single loud/viral source.
        Vera: quality = independent agreement, never view-count."""
        hits = self.query(text, branch_id=branch_id, top_k=pool, node_kind="finding")
        hits.sort(key=lambda h: (h.get("cross_source", False),
                                 h.get("corroboration_count", 1),
                                 h.get("score", 0)), reverse=True)
        return hits[:top_k]

    def set_tier(self, node_id: str, tier: str, *, branch_id: str = "main") -> None:
        """Patch a finding's confidence_tier in place (metadata-only, no re-embed).

        The tier is set by confidence.py from an EXTERNAL source count, never a
        model self-rating — this method just persists that decision. Preserves
        the vector and all other metadata (source_ids, urls, created_at)."""
        self._index.update(id=node_id, set_metadata={"confidence_tier": tier},
                           namespace=branch_id)

    def delete_node(self, node_id: str, *, branch_id: str = "main") -> None:
        """Remove a node — used by failure recovery to retract a bad finding."""
        self._index.delete(ids=[node_id], namespace=branch_id)

    def stats(self) -> dict:
        return self._index.describe_index_stats()
