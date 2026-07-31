"""Disagreement Engine (brief 26, idea 1) — the unique-identity organ.

Every answer engine collapses a question to one confident reply — which is exactly why they
structurally can't show you the SHAPE of a disagreement. This does the opposite: for a contested
question, it maps the controversy — the sides, the evidence each stands on, the CRUX where they
actually diverge — and then proposes what specific evidence would RESOLVE it. Nobody ships "here
is the structure of the argument, and here is what would end it."

Grounded-only (Vera): everything is built from the findings already on the map (synthesis buckets),
never invented. If there is no genuine disagreement, it returns an honest empty — it does NOT
fabricate a controversy (Noor). `what_would_resolve` output is labeled PROPOSED evidence, not fact.
"""
from __future__ import annotations

from .memory.memory_map import MemoryMap
from .memory.gap_detector import _reason_json
from . import synthesis as _synthesis


def _rows(bucket: list, limit: int = 12) -> str:
    return "\n".join(f"- {r['claim']}" for r in bucket[:limit]) or "(none)"


def disagreement_map(question: str, *, branch_id: str = "main",
                     mm: MemoryMap | None = None, top_k: int | None = None) -> dict:
    """Structured controversy map for a contested question. Returns
    {"contested": bool, "sides": [{"position","evidence":[...]}], "crux": str, "n_contested": int}.
    Built only from the contested + well-supported findings on the map; honest empty if none."""
    mm = mm or MemoryMap()
    buckets = _synthesis.gather_findings(question, branch_id=branch_id, top_k=top_k, mm=mm)
    contested = buckets.get("contested", [])
    supported = buckets.get("well-supported", [])
    if not contested:
        return {"contested": False, "sides": [], "crux": "",
                "n_contested": 0,
                "note": "No genuine disagreement on the map for this question."}
    prompt = (
        "You are mapping the STRUCTURE of a disagreement — not answering it. Using ONLY the "
        "findings below, lay out the opposing sides, the evidence each side stands on (drawn from "
        "the findings), and the CRUX: the single specific point the sides actually diverge on. Do "
        "NOT pick a winner, do NOT add outside knowledge, do NOT invent evidence not in the "
        "findings.\n\n"
        "ALSO report the directional LEAN: which side the GATHERED evidence currently tilts toward. "
        "Hard rules: this describes the balance of the evidence ON THE MAP, NEVER a probability that "
        "a side is right; if the evidence is genuinely even, say 'balanced'; weight corroborated / "
        "primary-source findings more than single-source ones.\n\n"
        f"QUESTION: {question}\n\n"
        f"CONTESTED findings (the disagreement):\n{_rows(contested)}\n\n"
        f"WELL-SUPPORTED findings (shared ground):\n{_rows(supported)}\n\n"
        'Return STRICT JSON: {"sides": [{"position": "...", "evidence": ["...", "..."]}], '
        '"crux": "the single point they diverge on", '
        '"lean": {"toward": "the position the evidence tilts to, or \'balanced\'", '
        '"magnitude": "slight/moderate/strong", "why": "one sentence, about the evidence not truth"}}')
    data = _reason_json(prompt)
    lean = data.get("lean", {}) if isinstance(data, dict) else {}
    if not isinstance(lean, dict):
        lean = {}
    if str(lean.get("magnitude", "")).lower() not in ("slight", "moderate", "strong"):
        lean["magnitude"] = "slight"
    return {"contested": True,
            "sides": data.get("sides", []) if isinstance(data, dict) else [],
            "crux": (data.get("crux", "") if isinstance(data, dict) else ""),
            "lean": {"toward": str(lean.get("toward", "balanced")).strip() or "balanced",
                     "magnitude": lean["magnitude"], "why": str(lean.get("why", "")).strip()},
            "n_contested": len(contested)}


def what_would_resolve(question: str, *, branch_id: str = "main",
                       mm: MemoryMap | None = None, top_k: int | None = None) -> dict:
    """For a contested question, propose the SPECIFIC evidence that would settle it. Returns
    {"contested": bool, "crux": str, "resolvers": [{"evidence","would_show"}]}. The resolvers are
    PROPOSED research directions (a study design, dataset, measurement, record) — clearly not
    claims of fact (Vera). Honest empty if there's nothing genuinely contested."""
    mm = mm or MemoryMap()
    dm = disagreement_map(question, branch_id=branch_id, mm=mm, top_k=top_k)
    if not dm.get("contested"):
        return {"contested": False, "crux": "", "resolvers": [],
                "note": "Nothing genuinely contested to resolve for this question."}
    sides_txt = "\n".join(
        f"- {s.get('position','')}" for s in dm.get("sides", [])) or "(sides unclear)"
    prompt = (
        "Below is the CRUX of a genuine disagreement and the opposing positions. Propose up to 4 "
        "SPECIFIC pieces of evidence that would actually RESOLVE it — a study design, dataset, "
        "measurement, experiment, or record that, if obtained, would show which side is right. "
        "These are PROPOSED research directions, NOT findings or claims of fact. Be concrete "
        "(name the kind of study/data), not generic ('more research needed').\n\n"
        f"QUESTION: {question}\nCRUX: {dm.get('crux','')}\nPOSITIONS:\n{sides_txt}\n\n"
        'Return STRICT JSON: {"resolvers": [{"evidence": "the specific study/data/measurement", '
        '"would_show": "what obtaining it would settle"}]}')
    data = _reason_json(prompt)
    resolvers = data.get("resolvers", []) if isinstance(data, dict) else []
    return {"contested": True, "crux": dm.get("crux", ""),
            "resolvers": resolvers,
            "note": "Resolvers are PROPOSED research directions, not established facts."}
