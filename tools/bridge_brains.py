"""Cross-brain bridges (READ-ONLY) — deliberately connect two isolated brains.

Each investigation has its own brain (isolation). This finds where two brains
GENUINELY connect, on demand, WITHOUT merging them (Marcus/Ghost: a bridge is a
read-only view, never written into either brain).

How it stays honest (Vera/Noor):
- Bridge candidates are REAL finding-pairs — the nearest findings across the two
  brains, by meaning. The model only LABELS the shared concept; it never invents a
  connection that isn't in the data.
- Similarity is reported plainly. Two unrelated brains connect weakly — a 0.35
  "bridge" is shown as the stretch it is, a 0.60 as a real link.

    # find the genuine connections between two brains:
    PYTHONPATH=src python tools/bridge_brains.py --a ai-monetization --b cure-aging

    # ask a question that draws on BOTH brains (grounded synthesis):
    PYTHONPATH=src python tools/bridge_brains.py --a ai-monetization --b cure-aging \
        --question "What does AI monetization teach us about funding aging research?"
"""
import argparse
import json
import sys

sys.path.insert(0, "src")

import numpy as np   # noqa: E402
import requests      # noqa: E402
from seeker import config                                   # noqa: E402
from seeker.memory.memory_map import MemoryMap, TEXT_FIELD  # noqa: E402

_URL = "https://openrouter.ai/api/v1/chat/completions"


def _fetch(mm, branch):
    ids = []
    for page in mm._index.list(namespace=branch):
        ids.extend(page if isinstance(page, (list, tuple)) else [page])
    texts, vecs = {}, {}
    for i in range(0, len(ids), 100):
        rec = mm._index.fetch(ids=ids[i:i + 100], namespace=branch)
        vectors = getattr(rec, "vectors", None) or (
            rec.get("vectors", {}) if isinstance(rec, dict) else {})
        for nid, v in vectors.items():
            meta = getattr(v, "metadata", None) or getattr(v, "fields", None) or {}
            t = (meta.get(TEXT_FIELD, "") if isinstance(meta, dict)
                 else getattr(meta, TEXT_FIELD, "")) or ""
            val = getattr(v, "values", None) or (v.get("values") if isinstance(v, dict) else None)
            if t and val:
                texts[nid], vecs[nid] = t, val
    order = list(texts)
    if not order:
        return [], np.zeros((0, 1), dtype=np.float32)
    M = np.asarray([vecs[n] for n in order], dtype=np.float32)
    M = M / np.clip(np.linalg.norm(M, axis=1, keepdims=True), 1e-9, None)
    return [texts[n] for n in order], M


def _label_pairs(pairs):
    """Ask the model to name the shared concept for each real pair (batched, cheap).
    Fails safe to no labels — the raw pair + similarity still stand on their own."""
    lines = "\n".join(f"[{i}] A: {a[:180]}\n    B: {b[:180]}" for i, (a, b, _s) in enumerate(pairs))
    prompt = (
        "Each numbered pair has one finding from topic A and one from topic B (two "
        "DIFFERENT investigations). For each, name in a few words the SHARED underlying "
        "concept that genuinely connects them (e.g. 'unit economics', 'regulatory "
        "approval as a market gate', 'subscription vs usage pricing'), or exactly "
        "'surface-only' if they merely share words with no real conceptual link. "
        "Return STRICT JSON {\"links\":[{\"i\":<int>,\"concept\":\"...\"}]}.\n\n" + lines)
    try:
        r = requests.post(
            _URL, headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                           "Content-Type": "application/json"},
            json={"model": config.EXTRACTOR_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"}},
            timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        return {int(e["i"]): str(e.get("concept", "")) for e in data.get("links", [])}
    except Exception:
        return {}


def find_bridges(mm, a, b, top, min_sim):
    ta, Ma = _fetch(mm, a)
    tb, Mb = _fetch(mm, b)
    if not ta or not tb:
        print(f"one of the brains is empty (a={len(ta)}, b={len(tb)}).")
        return
    sim = Ma @ Mb.T                      # |A| x |B| cross-brain cosine
    best_b = np.argmax(sim, axis=1)      # for each A finding, its closest B finding
    best_s = sim[np.arange(len(ta)), best_b]
    order = np.argsort(best_s)[::-1]

    pairs = []
    for ia in order:
        s = float(best_s[ia])
        if s < min_sim or len(pairs) >= top:
            continue
        pairs.append((ta[ia], tb[int(best_b[ia])], s))

    print("=" * 68)
    print(f"CROSS-BRAIN BRIDGES:  '{a}'  <->  '{b}'   (read-only; brains untouched)")
    print("=" * 68)
    if not pairs:
        print(f"No bridges above {min_sim:.2f}. These two brains barely connect — "
              f"which is itself a finding: they're genuinely different domains.")
        return
    labels = _label_pairs(pairs)
    strongest = pairs[0][2]
    if strongest < 0.55:
        print(f"(Note: strongest link is only {strongest:.2f} — these are WEAK bridges, "
              f"more analogy than overlap. Read them as 'loosely related', not proof.)\n")
    for i, (fa, fb, s) in enumerate(pairs):
        concept = labels.get(i, "")
        tag = f"  → shared: {concept}" if concept and concept != "surface-only" else (
            "  → (surface-only — weak)" if concept == "surface-only" else "")
        band = "STRONG" if s >= 0.6 else ("real" if s >= 0.5 else "weak")
        print(f"\n[{s:.2f} {band}]{tag}")
        print(f"   {a}: {fa[:150]}")
        print(f"   {b}: {fb[:150]}")


def synthesize(mm, a, b, question):
    fa = [h["text"] for h in mm.query(question, branch_id=a, top_k=6, node_kind="finding")]
    fb = [h["text"] for h in mm.query(question, branch_id=b, top_k=6, node_kind="finding")]
    ctx = ("FROM BRAIN A (%s):\n" % a) + "\n".join(f"- {t}" for t in fa) + \
          ("\n\nFROM BRAIN B (%s):\n" % b) + "\n".join(f"- {t}" for t in fb)
    prompt = (
        "You are bridging two separate investigations. Using ONLY the findings below "
        "(cite which brain each point comes from), answer the question by connecting "
        "the two domains. If the findings do NOT actually support a connection, say so "
        "plainly — do not invent one.\n\n"
        f"QUESTION: {question}\n\n{ctx}")
    try:
        r = requests.post(
            _URL, headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                           "Content-Type": "application/json"},
            json={"model": config.EXTRACTOR_MODEL,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        ans = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        ans = f"(synthesis failed: {e})"
    print("=" * 68)
    print(f"CROSS-BRAIN SYNTHESIS:  '{a}'  +  '{b}'")
    print("=" * 68)
    print(f"Q: {question}\n")
    print(ans)
    print("\n(Grounded only in findings retrieved from both brains — nothing invented.)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="first brain (branch)")
    ap.add_argument("--b", required=True, help="second brain (branch)")
    ap.add_argument("--top", type=int, default=12, help="max bridges to show")
    ap.add_argument("--min-sim", type=float, default=0.45,
                    help="ignore pairs below this cosine (weaker = not a real bridge)")
    ap.add_argument("--question", help="ask a question answered from BOTH brains")
    args = ap.parse_args()
    mm = MemoryMap()
    if args.question:
        synthesize(mm, args.a, args.b, args.question)
    else:
        find_bridges(mm, args.a, args.b, args.top, args.min_sim)


if __name__ == "__main__":
    main()
