"""Entity resolution — THE KEYSTONE (#23). Resolve name variants + misspellings to one canonical
entity so every downstream organ (synthesis, claim ledger, Quill, Connections) reads clean, resolved
people — instead of splitting one person into three ('Monica Reza' / 'Monica Jacinto' / 'Monica
Jacinto Reza') or adopting a garbled transcript spelling ('Schiavo' for the real 'Chavez').

Design (Marcus: the core needs NO LLM — deterministic record-linkage, cheap + testable):
  1. Collect every named-entity mention across findings, tagged AUTHORITATIVE (web/primary/structured)
     vs SPOKEN (youtube/podcast — error-prone).
  2. Cluster variants of the SAME entity: two names merge if they share the same FIRST and LAST token
     (handles variant middle names + subsets: Monica Reza = Monica Jacinto Reza; William Neil = William
     Lee McCasland), or one's tokens are a subset of the other's.
  3. Canonical form = the most COMPLETE variant, preferring an AUTHORITATIVE-sourced spelling.
  4. A spoken-only name that matches NO authoritative entity is SUSPECT (likely a transcript garble,
     e.g. 'Schiavo') — surfaced separately, NOT treated as a real entity (Vera: flag, don't silently
     drop). We can't auto-correct Schiavo->Chavez (different strings), but we can stop the garble from
     reaching the output as if it were real.
"""
from __future__ import annotations

import re

_AUTHORITATIVE = {"web", "primary_source", "structured_source", "secondary_review", "abstract"}


def proper_names(text: str) -> set:
    """THE canonical multi-word proper-name extractor (2-4 capitalised tokens). Single source of
    truth — imported by director + connections so the pattern can't drift across the codebase."""
    out = set()
    for m in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z.'&-]+){1,3})\b", text or ""):
        if len(m.split()) >= 2:
            out.add(m.strip())
    return out


_proper_names = proper_names   # back-compat alias


def _toks(name: str) -> list:
    return [t for t in re.split(r"\s+", name.lower().strip()) if t]


def _same_entity(a: str, b: str) -> bool:
    """True if two names likely refer to the same person: same first AND last token (variant/garbled
    middle), or one token-set is a subset of the other (shorter-form of the same name)."""
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return False
    if ta[0] == tb[0] and ta[-1] == tb[-1]:
        return True                                        # same given + surname (variant middle)
    sa, sb = set(ta), set(tb)
    return (sa <= sb or sb <= sa) and ta[0] == tb[0]       # one is a sub-name of the other, same given


def cluster_entities(mentions: list) -> list:
    """mentions: list of (name, is_authoritative). Returns [{canonical, variants, authoritative,
    suspect}]. Pure/deterministic — no network. 'suspect' = only-ever-seen in a spoken source AND
    matched no authoritative name."""
    # dedup mentions -> {name: authoritative_any}
    seen = {}
    for name, auth in mentions:
        n = " ".join(name.split())
        if n:
            seen[n] = seen.get(n, False) or bool(auth)
    # cluster: attach each name to an existing cluster it matches, else new cluster. Process
    # most-complete (most tokens) first so canonical anchors on the fullest form.
    clusters = []
    for name in sorted(seen, key=lambda x: (-len(_toks(x)), x)):
        placed = False
        for c in clusters:
            if any(_same_entity(name, v) for v in c["variants"]):
                c["variants"].append(name)
                c["authoritative"] = c["authoritative"] or seen[name]
                placed = True
                break
        if not placed:
            clusters.append({"variants": [name], "authoritative": seen[name]})
    out = []
    for c in clusters:
        # canonical: prefer an authoritative variant; among candidates take the most complete (longest)
        auth_vars = [v for v in c["variants"] if seen[v]]
        pool = auth_vars or c["variants"]
        canonical = max(pool, key=lambda v: (len(_toks(v)), len(v)))
        out.append({"canonical": canonical, "variants": sorted(set(c["variants"])),
                    "authoritative": c["authoritative"],
                    "suspect": (not c["authoritative"])})
    return out


def resolve_entities(findings: list) -> dict:
    """Resolve entities across a finding list. Each finding is a dict with 'claim' and optional
    'source_types'. Returns {"entities": [clusters], "canonical_map": {variant->canonical},
    "suspect_names": [spoken-only-unmatched]}. The canonical_map lets organs normalise names."""
    mentions = []
    for f in findings:
        claim = f.get("claim", "") if isinstance(f, dict) else getattr(f, "claim", "")
        stypes = f.get("source_types", []) if isinstance(f, dict) else []
        auth = any(s in _AUTHORITATIVE for s in (stypes or [])) if stypes else True  # default trust web
        for n in _proper_names(claim):
            mentions.append((n, auth))
    clusters = cluster_entities(mentions)
    cmap, suspect = {}, []
    for c in clusters:
        for v in c["variants"]:
            cmap[v] = c["canonical"]
        if c["suspect"]:
            suspect.append(c["canonical"])
    return {"entities": clusters, "canonical_map": cmap, "suspect_names": sorted(set(suspect))}
