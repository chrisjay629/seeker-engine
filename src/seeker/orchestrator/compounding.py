"""The compounding loop (brief 02 + closing the Phase 1 loop).

Mind reads the map -> picks the highest-value frontier question -> Adversarial
pre-flight -> Seeker hunt -> Memory Map grows -> Mind reads the NEW terrain ->
repeat. Each pass is smarter than the last; nothing restarts from zero. Every
node checkpoints to Supabase (thread_id = investigation), so the loop can sleep
and resume.

Assumes the map is already seeded (Recon Pass has run at least once).
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from ..mind.mind import generate_next_questions
from ..hunt.hunt import hunt
from ..memory.memory_map import MemoryMap
from ..memory.gap_detector import detect, detect_controversy, ClaimItem
from ..memory.confidence import promote_from_gap_result, CONTESTED


class LoopState(TypedDict, total=False):
    seed_question: str
    objective: str          # the Goal Generator's objective — anchors every question (component #0)
    branch_id: str
    cycle_n: int
    max_cycles: int
    current_question: str
    total_findings: int
    asked: list
    log: list
    status: str
    recency_years: int      # None/absent = all time; set from Truth Anchor freshness
    min_novelty: float      # saturation floor — stop early when new-of-kind rate drops below this
    stop_reason: str        # why the loop ended (for the human): saturated / cap / no_questions / empty


def mind_node(state: LoopState) -> dict:
    branch = state.get("branch_id", "main")
    ranked = generate_next_questions(
        state["seed_question"], branch_id=branch, n=5,
        cycle_n=state.get("cycle_n", 0), objective=state.get("objective", ""))
    picked = ""
    for r in ranked:
        if r["q"] not in state.get("asked", []):
            picked = r["q"]
            break
    return {"current_question": picked,
            "status": "mind_picked" if picked else "no_more_questions"}


def hunt_node(state: LoopState) -> dict:
    q = state.get("current_question", "")
    branch = state.get("branch_id", "main")

    # KB-FIRST (A1): before spending a whole research loop, check if the graded map already
    # holds a well-supported, cross-corroborated, still-fresh answer to this question. If so,
    # REUSE it and skip the hunt — the answer is already on the map (compounding win). Freshness
    # bound comes from the run's recency window (stale well-supported nodes get re-verified, not
    # blindly reused — Noor). Provenance is logged so the reuse is always visible (Luna).
    try:
        from ..mind.kb_first import kb_lookup
        _ry = state.get("recency_years")
        kb = kb_lookup(q, branch_id=branch,
                       max_age_days=(_ry * 365 if _ry else None))
    except Exception:
        kb = None
    if kb:
        asked = list(state.get("asked", [])) + [q]
        log = list(state.get("log", []))
        log.append({"cycle": state.get("cycle_n", 0) + 1, "q": q, "kb_reuse": True,
                    "reused_from": kb["finding_id"], "tier": kb["tier"],
                    "corroboration": kb["corroboration"], "age_days": kb["age_days"],
                    "survived": True, "upserted": 0, "merged": 0, "nested": 0,
                    "novelty": {}, "n_contested": 0,
                    "sources": [{"url": u, "type": "kb", "title": "♻ reused from KB"}
                                for u in kb["urls"][:5]]})
        return {"cycle_n": state.get("cycle_n", 0) + 1, "asked": asked, "log": log,
                "status": "kb_reused",
                "total_findings": state.get("total_findings", 0)}

    res = hunt(q, branch_id=branch, max_pages=3,
               recency_years=state.get("recency_years"))
    mm = MemoryMap()
    asked = list(state.get("asked", [])) + [q]

    # Actively fetch the OPPOSING side of the leading claims so genuine disagreements
    # have both sides on the map (Flag B / H7). Without this, contested can't fire —
    # you can't detect a contradiction that was never retrieved.
    try:
        from ..hunt import query_expansion
        counter = query_expansion.seek_counter_evidence(
            q, mm, branch_id=branch, recency_years=state.get("recency_years"))
        if counter:
            from ..memory.consolidation import upsert_findings_consolidated
            upsert_findings_consolidated(mm, counter)
    except Exception:
        pass

    # DISAGREEMENT DETECTION (Flag B, true fix): consolidation only ever promotes UP
    # via agreement — nothing in this loop marked Controversial, so Contested never
    # fired. Run cross-source disagreement detection on the findings the map now holds
    # for this question, and promote genuine contradictions to Controversial. Bounded
    # to the top findings relevant to q (cost/noise control). Each finding is its own
    # source_label, so a real cross-source disagreement is required.
    n_contested = 0
    try:
        hits = mm.query(q, branch_id=branch, top_k=15, node_kind="finding", hybrid=True)
        claims = [ClaimItem((h.get("text") or "").strip(),
                            source_label=f"finding:{str(h.get('id',''))[:8]}",
                            source_type=h.get("source_type") or "web")
                  for h in hits if (h.get("text") or "").strip()]
        if len(claims) >= 2:
            gap_result = detect([], q, branch_id=branch, extra_claims=claims)
            for g in gap_result.gaps:
                mm.upsert_gap(g)
            moved = promote_from_gap_result(mm, gap_result, branch_id=branch)
            n_contested = len(moved.get("contested", []))
        # Topic-level controversy (H7): catches genuine disagreement even when the
        # individual findings are neutral data points that only conflict when read
        # together — the case the pair-wise stance step misses.
        for d in detect_controversy(q, hits):
            for fid in d["finding_ids"]:
                try:
                    mm.set_tier(fid, CONTESTED, branch_id=branch)
                    n_contested += 1
                except Exception:
                    pass
    except Exception:
        pass  # never let disagreement detection break the hunt loop

    log = list(state.get("log", []))
    log.append({"cycle": state.get("cycle_n", 0) + 1, "q": q,
                "survived": res.survived_preflight, "upserted": res.n_upserted,
                "merged": res.n_merged, "nested": res.n_nested,
                "novelty": res.novelty, "n_contested": n_contested,
                "connected": getattr(res.post, "n_connected", 0),
                "n_web": res.n_web, "n_youtube": res.n_youtube,
                "n_expansion": res.n_expansion, "n_structured": res.n_structured,
                "structured_domains": res.structured_domains,
                "expansions": res.expansions, "sources": res.sources[:18]})
    return {"cycle_n": state.get("cycle_n", 0) + 1,
            "total_findings": state.get("total_findings", 0) + res.n_upserted,
            "asked": asked, "log": log, "status": "hunted"}


# Default saturation floor: when a round's new-of-kind rate falls below this, the
# frontier is exhausted and Seeker stops itself instead of burning cycles on rehash.
SATURATION_NOVEL_PCT = 0.10


def _route(state: LoopState) -> str:
    """Decide whether to run another round. Stops on: no more questions, the round
    cap (hard ceiling), or SATURATION — the novelty rate dropping below the floor.
    Vera's guard: a round with ZERO findings is a failure, not saturation — we stop
    but label it so it can't masquerade as 'done'."""
    if not state.get("current_question"):
        return END
    if state.get("cycle_n", 0) >= state.get("max_cycles", 3):
        return END

    log = state.get("log", [])
    if log and log[-1].get("kb_reuse"):
        return "mind"   # reused a KB answer — not an empty round; keep deepening (Noor)

    floor = state.get("min_novelty", SATURATION_NOVEL_PCT)
    if log:
        nov = log[-1].get("novelty") or {}
        total = sum(nov.values())
        if total == 0:
            return END   # empty round — a failure signal, not saturation (Vera)
        if (nov.get("novel", 0) / total) < floor:
            return END   # saturated — new-of-kind rate below the floor, stop paying
    return "mind"


def build_compounding_graph(checkpointer=None):
    g = StateGraph(LoopState)
    g.add_node("mind", mind_node)
    g.add_node("hunt", hunt_node)
    g.add_edge(START, "mind")
    g.add_conditional_edges("mind", lambda s: "hunt" if s.get("current_question") else END,
                            {"hunt": "hunt", END: END})
    g.add_conditional_edges("hunt", _route, {"mind": "mind", END: END})
    return g.compile(checkpointer=checkpointer)
