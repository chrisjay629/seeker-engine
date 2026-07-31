"""Data-path audit (Chris's question, 2026-07-30): is everything we gather ever actually reviewed?

THE QUESTION, in his words: "If we're only selecting certain data and leaving the others inside
Pinecone in the nodes and we're not reviewing it, then what's the point of gathering it?"

It turns out to be the right question. Every analysis organ reads the map through
synthesis.gather_findings(top_k=N). That is a SIMILARITY QUERY, not a review: it returns the N
nodes closest to the question and silently leaves the rest. On v19 that meant 500 of 677 nodes were
read and 177 — 26% of everything gathered, searched for, paid for — were never seen by synthesis,
the claim ledger, connections, profiles, disagreement, Quill or the report.

AND THE UNREAD PILE IS NOT JUNK. It held, among others:
    "William Neil McCasland vanished from his home in Albuquerque."      15 sources
    "McCasland's wife returned just before noon; he was already gone."    7 sources
    "Monica Jacinto Reza disappeared on Mount Waterman."                  8 sources
    "Carl Grillmair was found by LA County Fire paramedics outside his Llano home."  5 sources

IT IS ALSO NOT ALL EVIDENCE. The same pile held:
    "Terrence Johnson was charged with distributing heroin in SULLIVAN COUNTY"  <- a county, not
                                                                        Matthew James Sullivan
    "NOE Garcia was arrested for Interstate Transportation of Stolen Property"  <- wrong Garcia
    Oklahoma County prosecutors, a Florida tax-fraud task force, an FBI analyst in Colorado.

Which is the whole point: because nothing reviews the full set, the 15-source case fact and the
Tennessee drug case are treated identically — both simply sit there. Retrieval by similarity is
not review, and a top_k ceiling is a silent, arbitrary line drawn through the evidence.

This tool reports, for one branch: every lane that collected data, how much each contributed, how
much of the total is reachable inside the retrieval ceiling, and exactly what falls outside it.
Read-only.

    PYTHONPATH=src python tools/audit_data_paths.py --branch missing-scientists-v19
"""
import argparse
import json
import sys
from collections import Counter

sys.path.insert(0, "src")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    ap.add_argument("--top-k", type=int, default=500,
                    help="the retrieval ceiling the organs actually use")
    ap.add_argument("--question", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    from seeker import synthesis as syn
    from seeker.memory.memory_map import MemoryMap
    TEXT_FIELD = "text"

    mm = MemoryMap()
    q = args.question or ("For each named individual, verified status and documented cause — and is "
                          "there a genuine coordinated pattern or a coincidental cluster?")

    ids = []
    for page in mm._index.list(namespace=args.branch):
        ids.extend(page if isinstance(page, (list, tuple)) else [page])
    if not ids:
        print(f"no nodes in branch '{args.branch}'")
        return

    # ONE lossless reader, shared with everything else that needs the whole map (Zara: this
    # fetch-everything loop had been hand-copied into three places and would have drifted).
    meta = {f["id"]: {"text": f["claim"], "source_types": f["source_types"],
                      "urls": f["urls"], "confidence_tier": f["tier"],
                      "corroboration_count": f["corroboration"]}
            for f in syn.all_findings(args.branch, mm)}

    buckets = syn.gather_findings(q, branch_id=args.branch, top_k=args.top_k, mm=mm)
    seen = {f["id"] for lab in buckets for f in buckets[lab]}
    unread = [i for i in ids if i not in seen]

    def tally(subset, key):
        c = Counter()
        for nid in subset:
            m = meta.get(nid, {})
            vals = m.get(key) if key == "source_types" else [m.get(key, "(none)")]
            for v in (vals or ["(none)"]):
                c[v] += 1
        return c

    print(f"BRANCH: {args.branch}")
    print(f"  nodes gathered ............ {len(ids)}")
    print(f"  nodes any organ READS ..... {len(seen)}   (retrieval ceiling top_k={args.top_k})")
    print(f"  NEVER REVIEWED ............ {len(unread)}   ({100*len(unread)/len(ids):.0f}% of everything gathered)")

    print("\nCOLLECTION LANES — what each contributed, and how much of it is never read:")
    all_l, un_l = tally(ids, "source_types"), tally(unread, "source_types")
    print(f"  {'lane':22s} {'gathered':>9} {'unread':>7} {'% lost':>7}")
    for lane, n in all_l.most_common():
        u = un_l.get(lane, 0)
        print(f"  {lane:22s} {n:>9} {u:>7} {100*u/max(1,n):>6.0f}%")

    print("\nCONFIDENCE OF THE UNREAD PILE (is it junk, or is it evidence?):")
    for tier, n in tally(unread, "confidence_tier").most_common():
        print(f"  {tier:22s} {n}")

    strong = sorted(
        ((meta[i].get(TEXT_FIELD, ""), meta[i].get("confidence_tier"),
          float(meta[i].get("corroboration_count", 1) or 1)) for i in unread
         if meta.get(i, {}).get("confidence_tier") in ("Accepted", "Moderately Accepted")),
        key=lambda x: -x[2])
    print(f"\nWELL-SUPPORTED FINDINGS NEVER REVIEWED ({len(strong)}) — highest corroboration first:")
    for t, tier, c in strong[:15]:
        print(f"  [{c:.0f} src] {t[:110]}")

    if args.json:
        json.dump({"branch": args.branch, "total": len(ids), "read": len(seen),
                   "unread": len(unread), "by_lane": dict(all_l),
                   "unread_by_lane": dict(un_l),
                   "unread_texts": [meta[i].get(TEXT_FIELD, "") for i in unread]},
                  open(args.json, "w"), indent=2, default=str)
        print(f"\nwritten -> {args.json}")


if __name__ == "__main__":
    main()
