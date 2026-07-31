"""seeker-vet prototype — automated claim verifier (Gate 3 + 4).

Smallest reversible test of the OpenFactCheck-style idea: given a claim, retrieve
related evidence from our OWN map and have a model judge it AGAINST THAT EVIDENCE
(not its own opinion — spine-legit, like _contradicts). Then MEASURE it on cases
with KNOWN expected verdicts. Read-only; builds nothing into the engine.

    PYTHONPATH=src python tools/verifier_test.py
"""
import json
import sys

sys.path.insert(0, "src")

import requests
from seeker import config
from seeker.memory.memory_map import MemoryMap

_URL = "https://openrouter.ai/api/v1/chat/completions"


def verify(mm, claim, branch, k=6):
    hits = mm.query(claim, branch_id=branch, top_k=k + 2, node_kind="finding", hybrid=True)
    ev = [h["text"] for h in hits if h["text"].strip().lower() != claim.strip().lower()][:k]
    ctx = "\n".join(f"- {e}" for e in ev)
    prompt = (
        "Judge the CLAIM using ONLY the EVIDENCE below (other findings from our own "
        "knowledge base). Do NOT use outside knowledge — judge strictly against the "
        "evidence. Return STRICT JSON {\"verdict\":\"supported\"|\"contradicted\"|"
        "\"insufficient\",\"why\":\"one short line\"}. supported = evidence backs it; "
        "contradicted = evidence conflicts with it; insufficient = evidence doesn't "
        f"address it.\n\nCLAIM: {claim}\n\nEVIDENCE:\n{ctx}")
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


def main():
    mm = MemoryMap()
    # cases with KNOWN expected verdicts, tested on the main brain (AI cost/money data)
    cases = [
        ("supported", "OpenAI's inference costs exceed its reported revenues."),
        ("contradicted", "OpenAI is highly profitable and has negligible inference costs."),
        ("insufficient", "The Eiffel Tower in Paris is 330 meters tall."),
    ]
    print("=" * 68)
    print("VERIFIER TEST — expected vs actual (main brain)")
    print("=" * 68)
    right = 0
    for expected, claim in cases:
        verdict, why, n = verify(mm, claim, "main")
        ok = verdict == expected
        right += ok
        print(f"\n[{'PASS' if ok else 'FAIL'}] expected={expected} -> got={verdict}  (evidence={n})")
        print(f"   claim: {claim}")
        print(f"   why:   {why}")
    print(f"\n{'='*68}\nSCORE: {right}/{len(cases)} correct")


if __name__ == "__main__":
    main()
