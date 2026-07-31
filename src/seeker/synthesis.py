"""Synthesis organ — connect the dots (Noor's blind-spot flag).

The compounding loop is superb at GROWING the map — atomic findings, each labeled by
external evidence — but nothing ever reads the whole map back and says what it ADDS UP TO.
A pile of vetted facts is not an answer. This organ is the missing step: it pulls the
findings for a question off the Memory Map, buckets them BY THEIR STANDARD LABEL
(well-supported / contested / unverified / disproven), and composes an honest conclusion.

Spine (Vera): the labels are MECHANICAL — they come from each finding's confidence tier on
the map, not from the synthesizer grading itself. The LLM only writes the connective prose;
it may not promote a contested or unverified claim to certainty, and it must surface the
tensions explicitly rather than smoothing them into false consensus. Grounded-only: every
line must trace to a retrieved finding — no outside knowledge.
"""
from __future__ import annotations

from .memory.memory_map import MemoryMap
from .memory.confidence import standard_label
from .memory.gap_detector import _reason_json
from . import neutrality as _neutrality

# public four-label vocabulary, in the order a reader should meet them
_BUCKETS = ("well-supported", "contested", "unverified", "disproven")


def all_findings(branch_id: str = "main", mm: MemoryMap | None = None) -> list:
    """EVERY finding on the branch — no question, no similarity ranking, no ceiling.

    The counterpart to gather_findings, and the distinction is the point. gather_findings answers
    "what is most RELEVANT to this question?" and returns the top N; that is retrieval, and it is
    the right tool for writing an answer. It is the WRONG tool for review, because the nodes ranked
    N+1 and beyond are not judged and discarded — they are never looked at. On v19, 177 of 677
    nodes (26%) fell past every organ's ceiling, including "William Neil McCasland vanished from
    his home in Albuquerque" carrying 15 corroborating sources.

    Chris's question was the right one: what is the point of gathering evidence nobody reviews?
    This function exists so a reviewer can see all of it. Returns
    [{id, claim, source_types, urls, tier, corroboration}]. Fail-open to []."""
    mm = mm or MemoryMap()
    from .memory.memory_map import TEXT_FIELD
    try:
        ids = []
        for page in mm._index.list(namespace=branch_id):
            ids.extend(page if isinstance(page, (list, tuple)) else [page])
        out = []
        for i in range(0, len(ids), 100):
            rec = mm._index.fetch(ids=ids[i:i + 100], namespace=branch_id)
            vecs = getattr(rec, "vectors", None) or (
                rec.get("vectors", {}) if isinstance(rec, dict) else {})
            for nid, v in vecs.items():
                m = getattr(v, "metadata", None) or getattr(v, "fields", None) or {}
                m = dict(m) if not isinstance(m, dict) else m
                if m.get("node_kind") and m.get("node_kind") != "finding":
                    continue
                text = (m.get(TEXT_FIELD, "") or "").strip()
                if not text:
                    continue
                out.append({"id": nid, "claim": text,
                            "source_types": m.get("source_types", []) or [],
                            "urls": [u for u in (m.get("urls") or []) if u and u != "_"],
                            "tier": m.get("confidence_tier", "Speculative"),
                            "corroboration": float(m.get("corroboration_count", 1) or 1)})
        return out
    except Exception:
        return []


_EXCLUDED: set = set()


def set_excluded(ids) -> None:
    """Findings the case-file triage judged to be about a DIFFERENT person or a different case.

    Without this, triage was decorative: it recorded a verdict per finding and then every write-up
    organ went back to the map and re-read everything anyway, rejects included. A judgment nothing
    acts on is a judgment that did not happen. Run-scoped and set once, so a single decision reaches
    synthesis, the ledger, connections, profiles, disagreement and the report alike."""
    global _EXCLUDED
    _EXCLUDED = {str(i) for i in (ids or []) if i}


def gather_findings(question: str, *, branch_id: str | None = "main", top_k: int | None = None,
                    mm: MemoryMap | None = None) -> dict:
    """Pull findings off the map and bucket them by their STANDARD LABEL. Purely mechanical — the
    honest raw material the prose must respect.

    `top_k=None` (THE DEFAULT since 2026-07-30) means EVERY finding on the branch, ranked by nothing
    and cut by nothing. Pass an integer only when a small relevance slice is genuinely wanted.

    Why the default flipped: a ceiling here is a silent, arbitrary line drawn through the evidence.
    It does not judge and discard the findings past it — it never looks at them. On v19, 177 of 677
    nodes fell outside every organ's window, including "William Neil McCasland vanished from his
    home in Albuquerque" with 15 corroborating sources. Chris asked the question that settles it:
    what is the point of gathering evidence nobody reviews? Gathering is expensive and reading is
    cheap, so the default should be to read everything."""
    mm = mm or MemoryMap()
    if top_k is None:
        # LOSSLESS PATH: every finding, shaped like a query hit so the bucketing below is identical.
        hits = [{"id": f["id"], "text": f["claim"], "source_types": f["source_types"],
                 "urls": f["urls"], "confidence_tier": f["tier"],
                 "corroboration_count": f["corroboration"]}
                for f in all_findings(branch_id or "main", mm)
                if str(f["id"]) not in _EXCLUDED]
    else:
        hits = [h for h in mm.query(question, branch_id=branch_id, top_k=top_k,
                                    node_kind="finding", hybrid=True)
                if str(h.get("id")) not in _EXCLUDED]
    # Contested findings are the whole point but are often few and rank BELOW the top-k
    # relevance window — so the top-k query alone can miss them (headline feature silently
    # fails). Pull the contested-tier findings DIRECTLY and merge them in, so a genuine
    # disagreement always surfaces in the buckets. Bounded + deduped by id.
    from .memory.confidence import CONTESTED
    if top_k is not None:          # the lossless path already holds every contested finding
        seen_ids = {h.get("id") for h in hits}
        for h in mm.query(question, branch_id=branch_id, top_k=12,
                          node_kind="finding", tier=CONTESTED):
            if h.get("id") not in seen_ids:
                seen_ids.add(h.get("id"))
                hits.append(h)
    # `query` is eventually consistent: a tier just written by set_tier (e.g. a finding
    # promoted to Controversial in this same run) may not be reflected yet, so a contested
    # finding can arrive labeled Speculative. Re-read the AUTHORITATIVE tier by id (batched
    # fetch is strongly consistent) and let it win. Fixes the contested-propagation lag.
    truth = mm.get_metas([h.get("id") for h in hits], branch_id=branch_id)
    buckets: dict = {b: [] for b in _BUCKETS}
    for h in hits:
        text = (h.get("text") or "").strip()
        if not text:
            continue
        tier = (truth.get(h.get("id"), {}).get("confidence_tier")
                or h.get("confidence_tier", "Speculative"))
        buckets.setdefault(standard_label(tier), []).append(
            # URLs carried through (2026-07-30). The memory map stores every source's url on the
            # node — Ghost's provenance rule — and mm.query() returns them, but this dict dropped
            # the field one line later, so EVERY downstream organ was blind to provenance and the
            # published report cited nothing while Perplexity cited 18. The evidence was never
            # missing; it stopped here.
            {"id": h.get("id"), "claim": text, "source_types": h.get("source_types", []),
             "urls": [u for u in (h.get("urls") or []) if u and u != "_"],
             "corroboration": float(h.get("corroboration_count", 1) or 1)})
    return _demote_spoken_only(_normalize_names(buckets))


_SPOKEN = {"youtube", "podcast"}


def _demote_spoken_only(buckets: dict) -> dict:
    """Enforce brief 29 in DATAFLOW, not prompts (the 48h structural lesson): a finding sourced ONLY
    from spoken-word (YouTube/podcast) and NOT corroborated by any authoritative source is a LEAD, not
    a fact — cap it in the 'unverified' bucket so organs treat it as tentative (never well-supported /
    contested). Spoken-word that IS corroborated (its node also carries a web/primary source_type)
    keeps its tier. Fail-open. This is why the garbled 'Schiavo' claim must never read as a fact."""
    try:
        keep = {b: [] for b in buckets}
        moved = []
        for label, items in buckets.items():
            for f in items:
                st = set(f.get("source_types") or [])
                spoken_only = bool(st) and st <= _SPOKEN
                if spoken_only and label in ("well-supported", "contested"):
                    moved.append(f)
                else:
                    keep[label].append(f)
        keep.setdefault("unverified", [])
        keep["unverified"] = moved + keep["unverified"]
        return keep
    except Exception:
        return buckets


def _normalize_names(buckets: dict) -> dict:
    """KEYSTONE roll-out (#23): resolve entity name variants to their canonical form across ALL
    findings and rewrite the claim text — at the ONE chokepoint every organ reads through. So
    synthesis, claim ledger, disagreement, Quill and Connections all read canonical entities by
    default ('Monica Reza'/'Monica Jacinto' -> 'Monica Jacinto Reza'), no per-organ wiring, no DB
    rewrite. Deterministic; fail-open. (Distinct-string garbles like 'Schiavo' vs 'Chavez' remain —
    those need source-level fixing, not variant merging.)"""
    try:
        import re as _re
        from .entity_resolution import resolve_entities
        allf = [f for b in buckets.values() for f in b]
        cmap = resolve_entities(allf).get("canonical_map", {})
        # NEVER rewrite a variant that is a SUBSTRING of its canonical (fix 2026-07-28). The
        # resolver treats a shorter name as a "variant" of any longer one that starts with it, giving
        # pairs like 'United States' -> 'United States Border Patrol', 'Air Force' -> 'Air Force
        # General Neil', 'Human Rights' -> 'Human Rights Observatory'. Two harms:
        #   1. CORRUPTION OF SCOPE — rewriting 'United States' to 'United States Border Patrol' would
        #      mangle every mention of the country.
        #   2. DUPLICATION — substituting into text that already holds the full name repeats the
        #      tail: 'the Kansas City National Security Campus' -> 'the Kansas City National Security
        #      National Security Campus'. That produced 26 garbled claims in v18 ('Border Patrol
        #      Border Patrol agent', 'Human Rights Observatory Observatory', "Carl Grillmair's Llano
        #      Llano") which flowed into the report and made it unpublishable.
        # A shorter name is not a misspelling of a longer one — it is a more general name, and may be
        # correct as written. Only genuine variants (different spellings of the SAME string) rewrite.
        # The distinction that makes this safe: PERSON names expand at the FRONT (a given name is
        # added: 'Neil McCasland' -> 'William Neil McCasland') while ORG names expand at the END
        # (qualifiers are appended: 'United States' -> 'United States Border Patrol'). Only the
        # PREFIX case is dangerous — it both over-specifies a general name and duplicates the tail
        # when the text already holds the full form. So: allow suffix-expansion, block prefix.
        def _safe(v: str, c: str) -> bool:
            vl, cl = v.lower().strip(), c.lower().strip()
            if vl == cl:
                return False
            if vl in cl:
                return cl.endswith(vl)      # person-style front-expansion is fine; prefix is not
            if cl in vl:
                return False                # canonical shorter than the variant: never expand outward
            return True                     # genuinely different strings — a real variant
        pairs = sorted(((v, c) for v, c in cmap.items() if _safe(v, c)),
                       key=lambda p: -len(p[0]))
        if not pairs:
            return buckets
        for b in buckets.values():
            for f in b:
                claim = f["claim"]
                for variant, canon in pairs:
                    claim = _re.sub(r"\b" + _re.escape(variant) + r"\b", canon, claim)
                # BELT AND BRACES: collapse any adjacent repetition this pass (or a source) left
                # behind — 'Observatory Observatory', 'Llano Llano'. Cheap, deterministic, and it
                # catches the class even if a future mapping reintroduces it.
                claim = _re.sub(r"\b(\w+(?:\s+\w+){0,3})\s+\1\b", r"\1", claim, flags=_re.I)
                f["claim"] = claim
        return buckets
    except Exception:
        return buckets


def synthesize(question: str, *, branch_id: str = "main", top_k: int | None = None,
               mm: MemoryMap | None = None) -> dict:
    """Connect the dots into an honest conclusion. Returns
    {"conclusion", "buckets", "n_findings", "labels_present"}.

    The buckets are mechanical (from the map). The conclusion is LLM-composed but bound by
    the labels: it leads with what's well-supported, flags every contested point as
    unresolved (naming the tension), holds unverified claims as tentative, and calls out
    anything disproven. It never manufactures certainty the map doesn't have."""
    buckets = gather_findings(question, branch_id=branch_id, top_k=top_k, mm=mm)
    n = sum(len(v) for v in buckets.values())
    present = [b for b in _BUCKETS if buckets.get(b)]
    if n == 0:
        return {"conclusion": "(no findings on the map for this question yet)",
                "buckets": buckets, "n_findings": 0, "labels_present": []}

    # THE CAP IS GONE (2026-07-30, Chris: "remove the cap if possible").
    #
    # This read `rows[:14]`. With four buckets that meant the conclusion of the entire investigation
    # was written from at most 56 findings — on v19, 28 of 677. FOUR PERCENT of the evidence. The
    # top_k ceiling everyone had been arguing about was almost irrelevant next to it: retrieval
    # handed synthesis 500 findings and synthesis showed the model 28.
    #
    # It was never a size constraint. All 677 findings are 97k characters, about 24k tokens — a
    # fraction of any modern context window. The number 14 was a guess that hardened into a wall.
    #
    # Now every finding goes in. The budget below is a real ceiling for a genuinely enormous corpus,
    # not a default: at ~143 chars per claim it only engages past ~2,800 findings, and when it does
    # it keeps the BEST-CORROBORATED rather than whatever arrived first — a cut by evidence quality
    # instead of by arrival order. Whenever it fires it says so in the prompt, because a silent
    # truncation reads to the model as "this is everything" (Noor).
    _CHAR_BUDGET = 400_000

    def _fmt(label: str) -> str:
        rows = buckets.get(label, [])
        if not rows:
            return ""
        ordered = sorted(rows, key=lambda r: -float(r.get("corroboration", 1) or 1))
        kept, used = [], 0
        for r in ordered:
            line = f"  - {r['claim']}"
            if used + len(line) > _CHAR_BUDGET:
                break
            kept.append(line)
            used += len(line)
        note = ("" if len(kept) == len(rows) else
                f" (showing the {len(kept)} best-corroborated of {len(rows)} — corpus exceeds "
                f"the prompt budget)")
        return f"{label.upper()} findings{note}:\n" + "\n".join(kept)

    blocks = "\n\n".join(x for x in (_fmt(b) for b in _BUCKETS) if x)
    prompt = (
        "You are the synthesis step of an investigation. Below are atomic findings, already "
        "GROUPED by how much independent evidence backs each one. You did NOT assign these "
        "labels — they are fixed. Your job is ONLY to connect them into an honest conclusion.\n\n"
        "Hard rules:\n"
        "- Lead with the WELL-SUPPORTED throughline — what the strong evidence actually shows.\n"
        "- For every CONTESTED point, state the disagreement explicitly ('sources conflict on "
        "...'); do NOT resolve it or pick a side.\n"
        "- Hold UNVERIFIED findings as tentative ('one source suggests, not yet corroborated').\n"
        "- Name anything DISPROVEN as such.\n"
        "- Use ONLY the findings below — no outside knowledge, no invented certainty.\n"
        "- NAME FIDELITY: when naming a specific person, use the spelling as it appears in the most "
        "AUTHORITATIVE / primary / official findings. If a name is spelled several ways across "
        "sources, prefer the primary-source spelling and never adopt a variant from a lower-quality "
        "(e.g. transcript/social) source — misspelling a real person is a factual error.\n"
        "- Deliver the finding STRAIGHT (the doctor's-diagnosis rule): never soften, hedge, or "
        "cushion a finding because it is uncomfortable or sensitive; the tone may be plain and "
        "humane but the substance is unsoftened. No fluff, no filler, no moral editorializing. "
        "Keep figures with their per-capita/denominator basis and confounders — never a bare "
        "number.\n"
        "- 6-10 sentences. End with exactly: 'Confidence labels are set by external evidence, "
        "not by this summary.'\n\n"
        + _neutrality.protocol_block(question) + "\n"
        f"QUESTION: {question}\n\n{blocks}\n\n"
        'Return STRICT JSON: {"conclusion": "..."}')
    data = _reason_json(prompt)
    conclusion = (data.get("conclusion") or "").strip() or \
        "(synthesis unavailable — findings retrieved but no conclusion produced)"
    return {"conclusion": conclusion, "buckets": buckets,
            "n_findings": n, "labels_present": present}
