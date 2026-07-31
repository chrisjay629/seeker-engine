"""Hybrid retrieval MEASUREMENT (v5: evidence before adoption).

The hybrid-retrieval research says: vector search is strong on meaning but weak on
exact terms/numbers; BM25 nails exact terms; fusing them (Reciprocal Rank Fusion)
wins across query types. This tests that claim ON OUR OWN DATA — especially on the
exact-fact query vector search flubbed ("1-hour multiplier") — BEFORE we wire
anything into the engine. Read-only; nothing changed.

    PYTHONPATH=src python tools/hybrid_retrieval_test.py [--branch main]
"""
import argparse
import math
import re
import sys
from collections import Counter

sys.path.insert(0, "src")

from seeker.memory.memory_map import MemoryMap, TEXT_FIELD   # noqa: E402


def _tok(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = [_tok(d) for d in docs]
        self.N = len(self.docs)
        self.avgdl = sum(len(d) for d in self.docs) / max(self.N, 1)
        df = Counter()
        for d in self.docs:
            for w in set(d):
                df[w] += 1
        self.idf = {w: math.log(1 + (self.N - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def top(self, query, k):
        qt = _tok(query)
        scores = []
        for i in range(self.N):
            tf, dl = self.tf[i], len(self.docs[i])
            s = 0.0
            for w in qt:
                f = tf.get(w, 0)
                if f:
                    s += self.idf.get(w, 0) * (f * (self.k1 + 1)) / (
                        f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            scores.append(s)
        return sorted(range(self.N), key=lambda i: -scores[i])[:k]


def _rrf(ranked_lists, weights=None, k=60, top=5):
    """Weighted Reciprocal Rank Fusion: combine ranked id-lists (optionally
    weighting some higher — e.g. favor BM25 on exact-term queries)."""
    weights = weights or [1.0] * len(ranked_lists)
    score = {}
    for lst, w in zip(ranked_lists, weights):
        for rank, i in enumerate(lst):
            score[i] = score.get(i, 0.0) + w / (k + rank)
    return sorted(score, key=lambda i: -score[i])[:top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()
    mm = MemoryMap()

    # fetch all finding texts in the brain
    ids = []
    for page in mm._index.list(namespace=args.branch):
        ids.extend(page if isinstance(page, (list, tuple)) else [page])
    id2text = {}
    for i in range(0, len(ids), 100):
        rec = mm._index.fetch(ids=ids[i:i + 100], namespace=args.branch)
        vecs = getattr(rec, "vectors", None) or (rec.get("vectors", {}) if isinstance(rec, dict) else {})
        for nid, v in vecs.items():
            meta = getattr(v, "metadata", None) or getattr(v, "fields", None) or {}
            t = (meta.get(TEXT_FIELD, "") if isinstance(meta, dict) else getattr(meta, TEXT_FIELD, "")) or ""
            if t:
                id2text[nid] = t
    order = list(id2text)
    texts = [id2text[i] for i in order]
    pos = {nid: i for i, nid in enumerate(order)}
    print(f"[{args.branch}] built BM25 over {len(order)} findings\n")
    bm = BM25(texts)

    # test queries — exact-fact ones (vector's weakness) + a semantic control
    queries = [
        ("EXACT-FACT", "exact prompt cache write pricing multiplier for a 1-hour cache"),
        ("EXACT-FACT", "DeepSeek V4 flash price per million input tokens"),
        ("SEMANTIC (control)", "why do AI companies struggle to be profitable"),
    ]
    for kind, q in queries:
        print("=" * 72)
        print(f"[{kind}]  {q}")
        print("=" * 72)
        dense_ids = [h["id"] for h in mm.query(q, branch_id=args.branch, top_k=10, node_kind="finding")]
        dense_pos = [pos[i] for i in dense_ids if i in pos]
        bm_pos = bm.top(q, 10)
        even = _rrf([dense_pos, bm_pos], top=3)
        weighted = _rrf([dense_pos, bm_pos], weights=[1.0, 2.0], top=3)  # favor BM25
        print("\n  VECTOR-only top-3:")
        for i in dense_ids[:3]:
            print(f"     - {id2text.get(i,'')[:90]}")
        print("  BM25-only top-3:")
        for idx in bm_pos[:3]:
            print(f"     - {texts[idx][:90]}")
        print("  HYBRID even-weight top-3:")
        for idx in even:
            print(f"     - {texts[idx][:90]}")
        print("  HYBRID BM25-favored (1:2) top-3:")
        for idx in weighted:
            print(f"     - {texts[idx][:90]}")
        print()


if __name__ == "__main__":
    main()
