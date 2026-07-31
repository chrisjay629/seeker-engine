"""Export the Memory Map into Obsidian notes so it can be SEEN as a graph.

Seeker's knowledge lives in a cloud vector DB (Pinecone), which has no picture.
This reads every finding, writes each as a markdown note, and links each note to
its nearest neighbours (by meaning) — so Obsidian's Graph View lights up as a web
of what Seeker knows, naturally forming topic clusters. READ-ONLY on the map.

    PYTHONPATH=src python tools/export_to_obsidian.py [--branch main] [--neighbours 3]
                                                      [--limit N]

Output: Seeker-Vault/Map-Snapshot/  (one note per finding + an index). Re-runnable
(wipes and rewrites the snapshot folder). Gitignored — it's a generated view.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, "src")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Each brain (branch) exports to its OWN subfolder so topics never overwrite each
# other — filter the graph with e.g. path:Map-Snapshot/cure-aging to see one brain.
SNAP_ROOT = os.path.join(HERE, "Seeker-Vault", "Map-Snapshot")


def _slug(text: str, nid: str) -> str:
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()[:8]
    base = "-".join(words)[:60].strip("-") or "finding"
    return f"{base}--{nid[-6:]}"


def main():
    import numpy as np
    from seeker.memory.memory_map import MemoryMap, TEXT_FIELD

    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    ap.add_argument("--neighbours", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None, help="cap notes (for a quick look)")
    args = ap.parse_args()
    mm = MemoryMap()
    global OUT_DIR
    OUT_DIR = os.path.join(SNAP_ROOT, args.branch)

    # 1. pull every node id
    ids = []
    for page in mm._index.list(namespace=args.branch):
        ids.extend(page if isinstance(page, (list, tuple)) else [page])
    if args.limit:
        ids = ids[: args.limit]
    print(f"fetching {len(ids)} nodes...")

    # 2. fetch text + vector + metadata
    rec_text, rec_vec, rec_meta = {}, {}, {}
    for i in range(0, len(ids), 100):
        rec = mm._index.fetch(ids=ids[i:i + 100], namespace=args.branch)
        vectors = getattr(rec, "vectors", None) or (
            rec.get("vectors", {}) if isinstance(rec, dict) else {})
        for nid, v in vectors.items():
            meta = getattr(v, "metadata", None) or getattr(v, "fields", None) or {}
            meta = dict(meta) if not isinstance(meta, dict) else meta
            if meta.get("node_kind") and meta.get("node_kind") != "finding":
                continue
            rec_text[nid] = meta.get(TEXT_FIELD, "") or ""
            rec_meta[nid] = meta
            vals = getattr(v, "values", None) or (v.get("values") if isinstance(v, dict) else None)
            if vals:
                rec_vec[nid] = vals

    keep = [n for n in rec_text if n in rec_vec and rec_text[n].strip()]
    print(f"{len(keep)} findings with text + vector")

    # 3. nearest neighbours (cosine) for the links
    order = keep
    M = np.asarray([rec_vec[n] for n in order], dtype=np.float32)
    M = M / np.clip(np.linalg.norm(M, axis=1, keepdims=True), 1e-9, None)
    fname = {n: _slug(rec_text[n], n) for n in order}

    # 4. write folder
    if os.path.isdir(OUT_DIR):
        for f in os.listdir(OUT_DIR):
            os.remove(os.path.join(OUT_DIR, f))
    else:
        os.makedirs(OUT_DIR)

    K = args.neighbours
    for idx, n in enumerate(order):
        sims = M @ M[idx]
        sims[idx] = -1
        nn = np.argsort(sims)[::-1][:K]
        meta = rec_meta[n]
        tier = str(meta.get("confidence_tier", "Speculative")).replace(" ", "-")
        corr = meta.get("corroboration_count", 1)
        urls = [u for u in (meta.get("urls") or []) if u and u != "_"]
        links = "\n".join(f"- [[{fname[order[j]]}]]  _(similarity {sims[j]:.2f})_"
                          for j in nn if sims[j] > 0)
        body = [
            "---", f"tier: {tier}", f"sources: {len(urls)}",
            f"corroboration: {corr}", "---", "",
            f"# {rec_text[n]}", "",
            f"**Confidence:** {meta.get('confidence_tier','Speculative')}  ·  "
            f"**Corroborated by:** {corr} source(s)", "",
            "## Closest related findings", links or "_(none)_", "",
        ]
        if urls:
            body += ["## Where this came from"] + [f"- {u}" for u in urls[:8]]
        with open(os.path.join(OUT_DIR, fname[n] + ".md"), "w") as fh:
            fh.write("\n".join(body))

    # 5. index
    with open(os.path.join(OUT_DIR, "_INDEX.md"), "w") as fh:
        fh.write(f"# Seeker Memory Map — Snapshot\n\n"
                 f"{len(order)} findings exported from branch `{args.branch}`.\n\n"
                 f"Open **Graph View** (the graph icon, left sidebar) to see the web. "
                 f"Each dot is a fact; lines connect facts that are close in meaning, "
                 f"so clusters = topics Seeker has explored.\n")
    print(f"wrote {len(order)} notes + index to {OUT_DIR}")


if __name__ == "__main__":
    main()
