"""Lexical (BM25) retrieval + weighted fusion — the production hybrid layer.

Vector search is strong on meaning but weak on exact terms/numbers (measured: it
put the 5-minute price above the 1-hour price for a "1-hour" query). BM25 nails
exact terms. Fusing them (weighted Reciprocal Rank Fusion, favoring BM25) fixes the
exact-fact lookups WITHOUT hurting semantics — verified on our own data before
adoption (build-log 2026-07-08).

The BM25 index is built once per brain and CACHED (Cipher: never rebuild per query);
it rebuilds only when the brain's node count changes. Kept OUT of the calibrated
dedup path — this is for relevance-driven retrieval (the Mind, user search).
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .memory_map import TEXT_FIELD

_TOK = re.compile(r"[a-z0-9]+")
_CACHE: dict = {}   # branch -> (node_count, LexicalIndex)


def _tok(s: str):
    return _TOK.findall((s or "").lower())


def weighted_rrf(lists, weights=None, k=60, top=5):
    """Weighted Reciprocal Rank Fusion — merge ranked id-lists, optionally favoring
    one (BM25 gets more weight so its exact-term wins aren't diluted by vector)."""
    weights = weights or [1.0] * len(lists)
    score: dict = {}
    for lst, w in zip(lists, weights):
        for rank, i in enumerate(lst):
            score[i] = score.get(i, 0.0) + w / (k + rank)
    return sorted(score, key=lambda i: -score[i])[:top]


class LexicalIndex:
    def __init__(self, ids, fields):
        self.ids = ids
        self.fields = fields                      # parallel list of field dicts
        self.pos = {d: i for i, d in enumerate(ids)}
        docs = [_tok(f.get(TEXT_FIELD, "")) for f in fields]
        self.docs = docs
        self.N = len(docs)
        self.avgdl = sum(len(d) for d in docs) / max(self.N, 1)
        df = Counter()
        for d in docs:
            for w in set(d):
                df[w] += 1
        self.idf = {w: math.log(1 + (self.N - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.tf = [Counter(d) for d in docs]
        self.k1, self.b = 1.5, 0.75

    def top(self, query, k, node_kind=None):
        qt = _tok(query)
        scored = []
        for i in range(self.N):
            if node_kind and self.fields[i].get("node_kind") != node_kind:
                continue
            tf, dl = self.tf[i], len(self.docs[i])
            s = 0.0
            for w in qt:
                f = tf.get(w, 0)
                if f:
                    s += self.idf.get(w, 0) * (f * (self.k1 + 1)) / (
                        f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda x: -x[0])
        return [self.ids[i] for _s, i in scored[:k]]

    def as_hit(self, node_id):
        f = self.fields[self.pos[node_id]]
        return {"id": node_id, "score": 0.0, "text": f.get(TEXT_FIELD, ""),
                "node_kind": f.get("node_kind"), "status": f.get("status"),
                "confidence_tier": f.get("confidence_tier", "Speculative")}


def _brain_count(mm, branch) -> int:
    st = mm.stats()
    ns = getattr(st, "namespaces", None) or (
        st.get("namespaces") if isinstance(st, dict) else {}) or {}
    s = ns.get(branch)
    if s is None:
        return 0
    return int(getattr(s, "vector_count", None) or
               (s.get("vector_count") if isinstance(s, dict) else 0) or 0)


def lexical_index(mm, branch) -> LexicalIndex:
    """Cached per-brain BM25 index. Rebuilds only when the brain's size changes."""
    count = _brain_count(mm, branch)
    cached = _CACHE.get(branch)
    if cached and cached[0] == count:
        return cached[1]
    # (re)build — fetch all node texts + light metadata once
    ids = []
    for page in mm._index.list(namespace=branch):
        ids.extend(page if isinstance(page, (list, tuple)) else [page])
    keep_ids, fields = [], []
    for i in range(0, len(ids), 100):
        rec = mm._index.fetch(ids=ids[i:i + 100], namespace=branch)
        vectors = getattr(rec, "vectors", None) or (
            rec.get("vectors", {}) if isinstance(rec, dict) else {})
        for nid, v in vectors.items():
            meta = getattr(v, "metadata", None) or getattr(v, "fields", None) or {}
            meta = dict(meta) if not isinstance(meta, dict) else meta
            if meta.get(TEXT_FIELD):
                keep_ids.append(nid)
                fields.append(meta)
    idx = LexicalIndex(keep_ids, fields)
    _CACHE[branch] = (count, idx)
    return idx
