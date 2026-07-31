"""Bridge across ALL brains (READ-ONLY) — the serendipity scan.

Instead of picking two brains, this scans EVERY pair of your brains and surfaces
the strongest cross-topic connections in your whole knowledge base — the links you
never thought to look for. Reuses the honest pairwise engine (bridge_brains): real
finding-pairs only, the model just labels the shared concept, strength reported
plainly, nothing written into any brain.

Its power grows with how many SEPARATE brains you have — run investigations into
their own brains (--investigation) and this lights up with cross-topic gold.

    PYTHONPATH=src python tools/bridge_all.py [--min-sim 0.5] [--top 15] [--per-pair 3]
"""
import argparse
import os
import sys
from itertools import combinations

sys.path.insert(0, "src")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np   # noqa: E402
from seeker.memory.memory_map import MemoryMap   # noqa: E402
from bridge_brains import _fetch, _label_pairs    # noqa: E402


def _brains(mm):
    st = mm.stats()
    ns = getattr(st, "namespaces", None) or (
        st.get("namespaces") if isinstance(st, dict) else {}) or {}
    out = []
    for name, summ in ns.items():
        c = int(getattr(summ, "vector_count", None) or
                (summ.get("vector_count") if isinstance(summ, dict) else 0) or 0)
        if c > 0:
            out.append(name or "main")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-sim", type=float, default=0.5,
                    help="only surface bridges at least this strong")
    ap.add_argument("--top", type=int, default=15, help="max bridges to show overall")
    ap.add_argument("--per-pair", type=int, default=3, help="max bridges kept per brain-pair")
    args = ap.parse_args()
    mm = MemoryMap()

    brains = _brains(mm)
    print("=" * 70)
    print(f"SERENDIPITY SCAN — strongest connections across {len(brains)} brains")
    print(f"brains: {', '.join(brains)}")
    print("=" * 70)
    if len(brains) < 2:
        print("Only one brain so far — run investigations into separate brains "
              "(--investigation <name>) and this scan will find cross-topic links.")
        return

    cache = {b: _fetch(mm, b) for b in brains}   # each brain fetched ONCE (Cipher)

    all_bridges = []
    for a, b in combinations(brains, 2):
        ta, Ma = cache[a]
        tb, Mb = cache[b]
        if not ta or not tb:
            continue
        sim = Ma @ Mb.T
        best_b = np.argmax(sim, axis=1)
        best_s = sim[np.arange(len(ta)), best_b]
        for ia in np.argsort(best_s)[::-1][: args.per_pair]:
            s = float(best_s[ia])
            if s >= args.min_sim:
                all_bridges.append((s, a, b, ta[ia], tb[int(best_b[ia])]))

    all_bridges.sort(key=lambda x: -x[0])
    all_bridges = all_bridges[: args.top]

    if not all_bridges:
        print(f"\nNo bridges at/above {args.min_sim:.2f}. Your brains are genuinely "
              f"distinct domains — which is itself worth knowing. (Lower --min-sim to "
              f"see weaker, more analogical links.)")
        return

    labels = _label_pairs([(fa, fb, s) for (s, _a, _b, fa, fb) in all_bridges])
    print(f"\nTop {len(all_bridges)} cross-topic connections (strongest first):")
    for i, (s, a, b, fa, fb) in enumerate(all_bridges):
        concept = labels.get(i, "")
        band = "STRONG" if s >= 0.6 else "real"
        tag = f"  → shared: {concept}" if concept and concept != "surface-only" else \
              ("  → (surface-only)" if concept == "surface-only" else "")
        print(f"\n[{s:.2f} {band}]  {a}  <->  {b}{tag}")
        print(f"   {a}: {fa[:140]}")
        print(f"   {b}: {fb[:140]}")


if __name__ == "__main__":
    main()
