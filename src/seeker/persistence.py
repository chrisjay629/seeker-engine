"""Persistence — the 'researcher you employ' organ (brief 26, idea 4).

A frontier model answers once and forgets. Seeker's differentiator is the opposite: an
investigation is a PERSISTENT, growing body of work. Its map lives in Pinecone (per-branch
namespace) and its asked-questions ledger persists to disk, so an investigation can sleep and be
RESUMED later — the Mind reads the accumulated map, asks NEW frontier questions (the ledger stops
it re-asking old ones), and deepens. This module is the clean entry point for that: resume an
investigation, and report what it currently knows.

Uses the in-memory checkpointer for the resume run (the map + ledger already persist on their own;
the Postgres checkpointer drops on long runs — Marcus). A small on-disk registry remembers each
investigation's seed question + objective so you can resume by branch id alone.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from .memory.memory_map import MemoryMap
from .memory.confidence import standard_label

_REGISTRY = Path(__file__).resolve().parents[2] / "runs" / "investigations.json"


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _load_registry() -> dict:
    try:
        return json.loads(_REGISTRY.read_text())
    except Exception:
        return {}


def _save_registry(reg: dict) -> None:
    try:
        _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        _REGISTRY.write_text(json.dumps(reg, indent=2))
    except Exception:
        pass


def register(branch_id: str, seed_question: str, objective: str = "") -> None:
    """Record an investigation so it can be resumed by branch id alone."""
    reg = _load_registry()
    entry = reg.get(branch_id, {})
    entry.update({"branch_id": branch_id,
                  "seed_question": seed_question or entry.get("seed_question", ""),
                  "objective": objective or entry.get("objective", ""),
                  "created_at": entry.get("created_at", _now()),
                  "last_run_at": entry.get("last_run_at"),
                  "runs": entry.get("runs", 0)})
    reg[branch_id] = entry
    _save_registry(reg)


def _tier_counts(mm: MemoryMap, question: str, branch_id: str, top_k: int = 60) -> dict:
    """Approximate standing tier breakdown from the findings most relevant to the question.
    Supplements with a contested-tier query so contested findings (few, and often ranked below
    the window) aren't under-reported — same reason the synthesis buckets pull them directly."""
    from .memory.confidence import CONTESTED
    counts = {"well-supported": 0, "contested": 0, "unverified": 0, "disproven": 0}
    seen = set()
    rows = list(mm.query(question, branch_id=branch_id, top_k=top_k,
                         node_kind="finding", hybrid=True))
    rows += list(mm.query(question, branch_id=branch_id, top_k=15,
                          node_kind="finding", tier=CONTESTED))
    for h in rows:
        hid = h.get("id")
        if hid in seen:
            continue
        seen.add(hid)
        label = standard_label(h.get("confidence_tier", "Speculative"))
        counts[label] = counts.get(label, 0) + 1
    return counts


def investigation_state(branch_id: str, *, seed_question: str = "",
                        mm: MemoryMap | None = None) -> dict:
    """A standing snapshot of what an investigation KNOWS — without running anything.
    Reads the registry (seed/objective/last run) + the live map (finding count, tier breakdown).
    Lets you check in on a persistent investigation between runs."""
    mm = mm or MemoryMap()
    reg = _load_registry().get(branch_id, {})
    q = seed_question or reg.get("seed_question", "") or branch_id
    try:
        st = mm.stats()
        ns = getattr(st, "namespaces", None) or (
            st.get("namespaces") if isinstance(st, dict) else {}) or {}
        node_count = int(getattr(ns.get(branch_id), "vector_count", None)
                         or (ns.get(branch_id, {}).get("vector_count")
                             if isinstance(ns.get(branch_id), dict) else 0) or 0)
    except Exception:
        node_count = 0
    return {"branch_id": branch_id,
            "seed_question": reg.get("seed_question", ""),
            "objective": reg.get("objective", ""),
            "created_at": reg.get("created_at"),
            "last_run_at": reg.get("last_run_at"),
            "runs": reg.get("runs", 0),
            "node_count": node_count,
            "tier_counts": _tier_counts(mm, q, branch_id)}


def resume(branch_id: str, *, seed_question: str = "", objective: str = "",
           cycles: int = 2, recency_years: int | None = None,
           min_novelty: float = 0.10) -> dict:
    """Resume an existing investigation and DEEPEN it. Loads the accumulated map (Pinecone) +
    asked-ledger (disk); the Mind generates NEW frontier questions and runs `cycles` more rounds.
    Returns a DELTA: findings added this run, contested marked, questions asked, novelty, and the
    before/after node counts — i.e. 'what I found while you were gone.'"""
    from .orchestrator.compounding import build_compounding_graph
    mm = mm_local = MemoryMap()
    reg = _load_registry().get(branch_id, {})
    q = seed_question or reg.get("seed_question", "")
    obj = objective or reg.get("objective", "")
    if not q:
        return {"error": "no seed_question for this branch — pass seed_question= to resume it"}

    before = investigation_state(branch_id, seed_question=q, mm=mm_local)
    graph = build_compounding_graph(checkpointer=None)   # map+ledger persist; skip flaky Postgres
    final = graph.invoke(
        {"seed_question": q, "objective": obj, "branch_id": branch_id, "cycle_n": 0,
         "max_cycles": cycles, "total_findings": 0, "asked": [], "log": [],
         "recency_years": recency_years, "min_novelty": min_novelty},
        {"recursion_limit": max(20, cycles * 12 + 8)})
    log = final.get("log", []) or []
    after = investigation_state(branch_id, seed_question=q, mm=mm_local)

    register(branch_id, q, obj)
    r = _load_registry()
    r.setdefault(branch_id, {})
    r[branch_id]["last_run_at"] = _now()
    r[branch_id]["runs"] = r[branch_id].get("runs", 0) + 1
    _save_registry(r)

    return {"branch_id": branch_id,
            "cycles_run": final.get("cycle_n", 0),
            "findings_added": final.get("total_findings", 0),
            "contested_marked": sum(e.get("n_contested", 0) for e in log),
            "questions_asked": [e.get("q") for e in log if e.get("q")],
            "kb_reused": sum(1 for e in log if e.get("kb_reuse")),
            "node_count_before": before["node_count"],
            "node_count_after": after["node_count"],
            "tier_counts_after": after["tier_counts"]}
