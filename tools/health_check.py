"""Stabilization checkpoint — a fast, mostly-free health check of the core engine.

Run after any change to the retrieval / Mind / consolidation core to confirm nothing
broke. Read-only. A few cheap LLM calls (Mind + verifier); everything else is free.

    PYTHONPATH=src python tools/health_check.py [--branch main]
"""
import argparse
import sys
import traceback

sys.path.insert(0, "src")
sys.path.insert(0, ".claude/skills/seeker-verify")   # for verify()

_RESULTS = []


def check(name):
    def deco(fn):
        try:
            detail = fn()
            _RESULTS.append((True, name, detail))
        except Exception as e:
            _RESULTS.append((False, name, f"{type(e).__name__}: {e}"))
            traceback.print_exc()
    return deco


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()
    b = args.branch

    from seeker.memory.memory_map import MemoryMap
    mm = MemoryMap()

    @check("imports: core modules load")
    def _():
        import importlib
        for m in ["seeker.memory.memory_map", "seeker.memory.lexical",
                  "seeker.memory.novelty", "seeker.memory.consolidation",
                  "seeker.mind.mind", "seeker.mind.prefilter", "seeker.hunt.hunt"]:
            importlib.import_module(m)
        return "7 modules"

    @check("brains: all namespaces intact + counts")
    def _():
        st = mm.stats()
        ns = getattr(st, "namespaces", None) or (st.get("namespaces") if isinstance(st, dict) else {}) or {}
        total = sum(int(getattr(v, "vector_count", 0) or (v.get("vector_count", 0) if isinstance(v, dict) else 0)) for v in ns.values())
        return f"{len(ns)} brains, {total} findings"

    @check("retrieval: vector-only query returns hits")
    def _():
        r = mm.query("inference cost", branch_id=b, top_k=3, node_kind="finding")
        assert r and r[0]["text"], "no vector hits"
        return f"{len(r)} hits, top score {r[0]['score']}"

    @check("retrieval: HYBRID query returns hits (new path)")
    def _():
        r = mm.query("exact 1-hour cache write multiplier", branch_id=b, top_k=3,
                     node_kind="finding", hybrid=True)
        assert r and r[0]["text"], "no hybrid hits"
        return f"{len(r)} hits, top: {r[0]['text'][:45]}"

    @check("lexical: BM25 index builds + cached")
    def _():
        from seeker.memory.lexical import lexical_index
        idx = lexical_index(mm, b)
        assert idx.N > 0, "empty index"
        return f"{idx.N} docs indexed"

    @check("prefilter: novelty-steering (calibrated) points the right way")
    def _():
        from seeker.mind import prefilter as P
        cov = P.score("prompt caching cost multipliers", mm=mm, branch_id=b)["frontier"]
        fro = P.score("how do data-center carbon emissions and grid location affect "
                      "inference cost", mm=mm, branch_id=b)["frontier"]
        off = P.score("axolotl salamander mating behavior", mm=mm, branch_id=b)["frontier"]
        assert cov <= 0.15, f"covered not demoted (={cov})"
        assert fro >= 0.9, f"frontier not rewarded (={fro})"
        assert off <= 0.4, f"off-map not demoted (={off})"
        return f"covered={cov} · frontier={fro} · off-map={off} — steering OK"

    @check("novelty: instrument scores a finding")
    def _():
        from seeker.memory import novelty
        r = novelty.score_finding(mm, "LLM inference is memory-bandwidth bound", branch_id=b)
        assert r["tier"] in novelty.TIERS
        return f"tier={r['tier']}, nearest={r['nearest_score']}"

    @check("Mind: generates questions (max_tokens fix)")
    def _():
        from seeker.mind.mind import generate_next_questions
        qs = generate_next_questions("how to reduce LLM cost", branch_id=b, n=3)
        assert len(qs) >= 1, "Mind returned no questions"
        return f"{len(qs)} questions generated"

    @check("seeker-verify: verifier still runs (spine)")
    def _():
        from verify_brain import verify
        v, why, n = verify(mm, "OpenAI's inference costs exceed its revenues.", b)
        assert v in ("supported", "contradicted", "insufficient"), f"bad verdict {v}"
        return f"verdict={v} on {n} evidence"

    print("=" * 60)
    print(f"STABILIZATION CHECKPOINT — branch '{b}'")
    print("=" * 60)
    for ok, name, detail in _RESULTS:
        print(f"  {'✅' if ok else '❌'} {name}")
        print(f"       {detail}")
    passed = sum(1 for ok, _, _ in _RESULTS if ok)
    print("-" * 60)
    print(f"  {passed}/{len(_RESULTS)} checks passed")
    print("  ALL HEALTHY — safe to keep building." if passed == len(_RESULTS)
          else "  ⚠️ FAILURES above — fix before building on top.")


if __name__ == "__main__":
    main()
