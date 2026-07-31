"""seeker-verify — READ-ONLY claim checker (spine defense).

Checks a brain's findings against the rest of its OWN map and flags the ones that
CONTRADICT the evidence (likely errors or poisoning) for human review. Judges each
claim strictly against retrieved evidence — not the model's own opinion (spine-legit,
verified 3/3 in the seeker-vet run, build-log 2026-07-08).

Never deletes or changes anything — it flags; a human decides. Prioritizes
low-corroboration (Speculative) findings, the highest error/poisoning risk (Ghost).

    PYTHONPATH=src python tools/verify_brain.py --branch main [--limit 40] [--tier speculative|all]
"""
import argparse
import json
import sys

sys.path.insert(0, "src")

import requests   # noqa: E402
from seeker import config                                   # noqa: E402
from seeker.memory.memory_map import MemoryMap, TEXT_FIELD  # noqa: E402

_URL = "https://openrouter.ai/api/v1/chat/completions"


def verify(mm, claim, branch, k=6):
    """Judge `claim` strictly against retrieved MAP evidence. Returns
    (verdict, why, n_evidence). verdict in supported/contradicted/insufficient."""
    hits = mm.query(claim, branch_id=branch, top_k=k + 2, node_kind="finding", hybrid=True)
    ev = [h["text"] for h in hits if h["text"].strip().lower() != claim.strip().lower()][:k]
    ctx = "\n".join(f"- {e}" for e in ev)
    prompt = (
        "Judge the CLAIM using ONLY the EVIDENCE below (other findings from our own "
        "knowledge base). Do NOT use outside knowledge. Return STRICT JSON "
        "{\"verdict\":\"supported\"|\"contradicted\"|\"insufficient\",\"why\":\"one short line\"}. "
        "supported = evidence backs it; contradicted = evidence conflicts; insufficient "
        f"= evidence doesn't address it.\n\nCLAIM: {claim}\n\nEVIDENCE:\n{ctx}")
    try:
        r = requests.post(_URL, headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                                         "Content-Type": "application/json"},
                          json={"model": config.EXTRACTOR_MODEL,
                                "messages": [{"role": "user", "content": prompt}],
                                "response_format": {"type": "json_object"}},
                          timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        d = json.loads(r.json()["choices"][0]["message"]["content"])
        return d.get("verdict", "?"), d.get("why", ""), len(ev)
    except Exception as e:
        return "error", str(e)[:80], len(ev)


def _findings(mm, branch):
    ids = []
    for page in mm._index.list(namespace=branch):
        ids.extend(page if isinstance(page, (list, tuple)) else [page])
    out = []
    for i in range(0, len(ids), 100):
        rec = mm._index.fetch(ids=ids[i:i + 100], namespace=branch)
        vectors = getattr(rec, "vectors", None) or (rec.get("vectors", {}) if isinstance(rec, dict) else {})
        for nid, v in vectors.items():
            meta = getattr(v, "metadata", None) or getattr(v, "fields", None) or {}
            meta = dict(meta) if not isinstance(meta, dict) else meta
            if meta.get("node_kind", "finding") == "finding" and meta.get(TEXT_FIELD):
                out.append((nid, meta[TEXT_FIELD], meta.get("confidence_tier", "Speculative")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    ap.add_argument("--limit", type=int, default=40, help="max findings to check (1 LLM call each)")
    ap.add_argument("--tier", choices=["speculative", "all"], default="speculative",
                    help="which findings to prioritize (default: riskiest single-source first)")
    args = ap.parse_args()
    mm = MemoryMap()

    findings = _findings(mm, args.branch)
    if args.tier == "speculative":
        findings.sort(key=lambda f: 0 if str(f[2]).lower().startswith("spec") else 1)
    targets = findings[: args.limit]

    print("=" * 70)
    print(f"seeker-verify — {args.branch}  (checking {len(targets)} of {len(findings)} "
          f"findings, {args.tier}-first)  READ-ONLY")
    print("=" * 70)
    tally = {"supported": 0, "contradicted": 0, "insufficient": 0, "error": 0}
    flagged, unverifiable = [], []
    for k, (nid, claim, tier) in enumerate(targets, 1):
        verdict, why, n = verify(mm, claim, args.branch)
        tally[verdict] = tally.get(verdict, 0) + 1
        if verdict == "contradicted":
            flagged.append((claim, why, tier))
        elif verdict == "insufficient":
            unverifiable.append((claim, tier))
        if k % 10 == 0:
            print(f"  ...{k}/{len(targets)}")

    print(f"\nresults: {tally['supported']} supported · "
          f"{tally['contradicted']} CONTRADICTED · {tally['insufficient']} insufficient · "
          f"{tally['error']} errors")

    print(f"\n⚠️  FLAGGED — contradict the map (human review; NOTHING deleted): {len(flagged)}")
    for claim, why, tier in flagged:
        print(f"   [{tier}] {claim[:110]}")
        print(f"           why: {why}")
    if unverifiable:
        print(f"\n○  unverifiable — no supporting evidence in this brain: {len(unverifiable)}")
        for claim, tier in unverifiable[:10]:
            print(f"   [{tier}] {claim[:110]}")
    print("\nNothing was changed. A human decides what to do with the flags.")


if __name__ == "__main__":
    main()
