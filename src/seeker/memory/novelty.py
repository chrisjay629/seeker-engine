"""Novelty-of-kind instrument (Phase 2, brief 07) — READ-ONLY.

Scores how NEW a finding is relative to the existing map, purely from map geometry
(nearest-neighbour cosine) — never a model self-report. The map is the external
referent; the model never declares itself novel (spine).

This is an INSTRUMENT, not a behaviour: it labels and counts, it changes nothing
about what gets stored. Wired to piggyback on the nearest-neighbour query that
consolidation already runs (no extra queries/cost).

THRESHOLDS ARE PLACEHOLDERS pending calibration to the mm.query scale (query->passage
asymmetric; identical text self-matches ~0.65 on this embedder, not 1.0). The smoke
test (calibration/novelty_smoke.py) prints the real nearest-neighbour distribution so
these get set from data, exactly like the 0.60 dedup threshold was — do NOT treat
0.30/0.60 as final.
"""
# Calibrated v1 from the live map's nearest-neighbour distribution
# (calibration/novelty_smoke.py, 2026-07-07): min 0.28 / median 0.50 / max 0.82.
# Natural breaks: left tail < 0.40 (novel, ~17%), bulk 0.40-0.60 (incremental, ~64%),
# right >= 0.60 (redundant, ~19%, matches the dedup threshold + the redundant probe
# at 0.61). NOTE: map-relative — a topically-tight map clusters higher; re-run the
# smoke test and re-set these as the map's breadth changes.
REDUNDANT_AT = 0.60    # >= this: dedup/nesting territory — not new
INCREMENTAL_AT = 0.40  # >= this (and < redundant): thickens a known cluster
# < INCREMENTAL_AT: novel-of-kind (lands in sparsely-populated space)

TIERS = ("novel", "incremental", "redundant")


def tier(nearest_score: float) -> str:
    """Map a nearest-neighbour cosine to a novelty tier (higher score = less novel)."""
    if nearest_score >= REDUNDANT_AT:
        return "redundant"
    if nearest_score >= INCREMENTAL_AT:
        return "incremental"
    return "novel"


def score_finding(mm, claim: str, *, branch_id: str = "main") -> dict:
    """Read-only novelty score for one claim vs the existing map. Standalone path
    (used by the smoke test / audits); the hunt path piggybacks on consolidation's
    existing nearest-neighbour query instead of calling this again."""
    hits = mm.query(claim, branch_id=branch_id, top_k=1, node_kind="finding")
    best = hits[0] if hits else None
    s = float(best["score"]) if best else 0.0
    return {"tier": tier(s), "nearest_score": s,
            "nearest_id": best["id"] if best else None}


def empty_tally() -> dict:
    return {t: 0 for t in TIERS}
