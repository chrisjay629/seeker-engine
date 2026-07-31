"""The Mind pre-filter (brief 05) — cost discipline on question selection.

Four MECHANICAL scores computed from the Memory Map (no model grading). Only
high-scoring candidates reach the expensive Mind / Seeker dispatch.

  1. disagreement   — max cosine similarity to an existing disagreement gap node
  2. frontier       — NOVELTY-STEERING (calibrated re-ship 2026-07-10). Rewards
                      questions targeting NEW-but-CONNECTED ground; demotes covered
                      ground (re-tilling) AND far-off-map questions (irrelevant, the
                      "frog"). Non-monotonic — steers toward the edge of the known,
                      not into the void.
  3. load_bearing   — how many existing finding nodes sit near this question
                      (normalized) — closing it touches more of the map
  4. tractability   — heuristic: some existing grounding makes a question more
                      answerable now; pure blue-sky scores lower

Calibration (calibration/frontier_smoke.py, measured from 477 REAL Mind questions):
top_find here is QUERY->passage similarity — a lower/compressed scale than the
passage->passage scale novelty.py uses (borrowing THOSE thresholds is what broke the
first attempt — build-log 2026-07-09). Real distribution: median 0.35, p75 0.41,
p90 0.49; off-map probes ~0.15. So covered questions sit ~>=0.42 (top quartile),
the productive frontier band is ~0.24-0.42, and <0.16 is off-map. VECTOR-ONLY on
purpose: this is a geometric distance measurement; hybrid retrieval (BM25 fusion,
score 0.0 on promoted hits) corrupts it. Weights unchanged (no guessed re-tuning).
"""
from __future__ import annotations

from ..memory.memory_map import MemoryMap

_NEAR = 0.40          # similarity counted as "related"
_LOAD_CAP = 8         # normalization cap for load-bearing

# CALIBRATED to the query->passage scale (frontier_smoke.py). Do not swap in
# novelty.py's passage-scale numbers — different measurement.
_COVERED_AT = 0.42    # >= this: covered ground (top ~quartile of real questions)
_FRONTIER_LO = 0.24   # connected-frontier band lower edge (~p25)
_EDGE_LO = 0.16       # below this: off-map / irrelevant (probe floor ~0.15)

_W = {"disagreement": 0.25, "frontier": 0.35, "load_bearing": 0.20, "tractability": 0.20}


def _frontier(top_find: float) -> float:
    """Novelty-steering signal on the calibrated query->passage scale."""
    if top_find >= _COVERED_AT:       # covered -> steer AWAY (re-tilling)
        return 0.15
    if top_find >= _FRONTIER_LO:      # connected frontier -> the sweet spot
        return 1.0
    if top_find >= _EDGE_LO:          # novel edge, still somewhat connected
        return 0.60
    return 0.35                       # far off-map -> probably irrelevant


def score(question: str, *, mm: MemoryMap | None = None,
          branch_id: str = "main") -> dict:
    mm = mm or MemoryMap()
    findings = mm.query(question, branch_id=branch_id, top_k=_LOAD_CAP,
                        node_kind="finding")
    gaps = mm.query(question, branch_id=branch_id, top_k=3, node_kind="gap")

    top_find = max((h["score"] for h in findings), default=0.0)
    top_gap = max((h["score"] for h in gaps), default=0.0)
    near_count = sum(1 for h in findings if h["score"] >= _NEAR)

    disagreement = round(top_gap, 4)
    frontier = round(_frontier(top_find), 4)
    load_bearing = round(min(near_count / _LOAD_CAP, 1.0), 4)
    # some grounding aids answerability; fully novel questions are harder now
    tractability = round(0.4 + 0.6 * load_bearing, 4)

    combined = round(
        _W["disagreement"] * disagreement + _W["frontier"] * frontier
        + _W["load_bearing"] * load_bearing + _W["tractability"] * tractability, 4)

    return {"disagreement": disagreement, "frontier": frontier,
            "novelty": frontier,   # back-compat alias for the question ledger
            "load_bearing": load_bearing, "tractability": tractability,
            "combined": combined}
