"""The investigation loop as a LangGraph state graph (brief 02).

One cycle: recon -> gap_detect -> (checkpoint after each node). LangGraph writes
a checkpoint to Supabase on every node completion, so a run survives shutdown at
any point and resumes from where it stopped (thread_id = investigation id).

The Orchestrator coordinates; it never judges quality (spine). branch_id and
rate_limit_bucket ride in state so introspective runs stay isolated.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from ..models import _id, SourceResponse
from ..recon import sources, youtube
from ..memory.memory_map import MemoryMap
from ..memory.gap_detector import detect
from ..memory.confidence import promote_from_gap_result


class InvestigationState(TypedDict, total=False):
    question: str
    question_id: str
    branch_id: str
    rate_limit_bucket: str
    cycle_n: int
    with_youtube: bool
    # progress (kept lean so checkpoints stay small)
    responses: list          # list[dict]: {source_label, source_type, ok, raw_text}
    n_sources_ok: int
    n_youtube_findings: int
    n_claims: int
    n_gaps: int
    n_corroborations: int
    n_promoted: int
    n_contested: int
    status: str


def recon_node(state: InvestigationState) -> dict:
    q = state["question"]
    qid = state.get("question_id") or _id("q")
    branch = state.get("branch_id", "main")
    bucket = state.get("rate_limit_bucket", "main")

    responses = sources.sweep(q, qid, branch_id=branch, rate_limit_bucket=bucket)
    lean = [{"source_label": r.source_label, "source_type": r.source_type,
             "ok": r.ok, "raw_text": r.raw_text} for r in responses]

    yt_n = 0
    if state.get("with_youtube"):
        mm = MemoryMap()
        yt = youtube.youtube_channel(q, branch_id=branch)
        yt_n = mm.upsert_findings(yt, branch_id=branch)

    return {"question_id": qid, "responses": lean,
            "n_sources_ok": sum(1 for r in responses if r.ok),
            "n_youtube_findings": yt_n, "status": "recon_done"}


def gap_node(state: InvestigationState) -> dict:
    q = state["question"]
    qid = state["question_id"]
    branch = state.get("branch_id", "main")

    # reconstruct minimal SourceResponse objects the detector needs
    reconstructed = [
        SourceResponse(qid, d["source_type"], d["source_label"], d["raw_text"],
                       branch_id=branch)
        for d in state.get("responses", []) if d["ok"]
    ]

    # Contested-firing fix: feed the retrieved findings (where contested material
    # lives) into disagreement detection as first-class claims — each its own
    # source so genuine cross-source disagreement is required. Bounded to the
    # top findings most relevant to this question to control cost/noise.
    mm = MemoryMap()
    from ..memory.gap_detector import ClaimItem
    extra_claims = []
    for h in mm.query(q, branch_id=branch, top_k=12, node_kind="finding"):
        txt = (h.get("text") or "").strip()
        if not txt:
            continue
        extra_claims.append(ClaimItem(
            txt, source_label=f"finding:{str(h.get('id',''))[:8]}",
            source_type=h.get("source_type") or "web"))

    result = detect(reconstructed, q, branch_id=branch, extra_claims=extra_claims)

    for g in result.gaps:
        mm.upsert_gap(g)

    # corroboration/disagreement -> confidence-tier movement (external count only)
    moved = promote_from_gap_result(mm, result, branch_id=branch)

    return {"n_claims": result.n_claims, "n_gaps": len(result.gaps),
            "n_corroborations": len(result.corroborations),
            "n_promoted": len(moved["promoted"]),
            "n_contested": len(moved["contested"]),
            "cycle_n": state.get("cycle_n", 0) + 1, "status": "cycle_complete"}


def build_graph(checkpointer=None):
    g = StateGraph(InvestigationState)
    g.add_node("recon", recon_node)
    g.add_node("gap_detect", gap_node)
    g.add_edge(START, "recon")
    g.add_edge("recon", "gap_detect")
    g.add_edge("gap_detect", END)
    return g.compile(checkpointer=checkpointer)
