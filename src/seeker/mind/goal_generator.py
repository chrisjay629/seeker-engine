"""Goal Generator (component #0 — the most upstream lever).

Turns a RAW SUBJECT into a sharp investigation OBJECTIVE that anchors everything
downstream: the Mind's questions, the hunt, and the Synthesis organ. A good goal
scopes the whole run; a vague one wastes it (Zara: the #0 lever).

Design commitments (council, 2026-07-11):
  - Suggest, don't force (Luna): propose 2-3 candidate goals, each stating what it
    would YIELD; the user picks / edits / confirms.
  - Honest ceiling (Elara/Vera): a goal orients toward surfacing NON-OBVIOUS,
    under-cross-referenced connections and FLAGS them as such — it never promises
    to "discover new truth." Absence of a prior link is not proof of novelty.
  - Optimize for verifiable, non-obvious CONNECTIONS, not volume (Vera): "most
    data" is the wrong target.
  - A goal may be unreachable; the mission is to get as CLOSE as possible, measure
    that proximity honestly, and CHECKPOINT the user rather than research forever
    (Gambit, 2026-07-11).

STATUS: scaffold. The professional goal-formulation DOCTRINE (FINER, PICO, GQM,
Key Intelligence Topics, saturation/stopping rules) is codified from brain
`goal-formulation` and ratified by the council BEFORE this is wired into the live
graph. Not yet in the investigation loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..memory.gap_detector import _cheap_json
from ..memory.confidence import standard_label

# Codified from brain `goal-formulation` (56 findings), under the epistemic standard.
# Kept as one tight block so the LLM prompt stays bounded (Marcus: contain token cost).
# Honest ceiling (Vera, from a well-supported finding): FINER/PICO are widely-used
# STRUCTURING SCAFFOLDS, not proven quality guarantees — one study found full PICO
# even LOWERED search recall. So use them to structure and vet, never as a promise.
_DOCTRINE = (
    "Follow professional goal-formulation tradecraft (scaffolds to structure the "
    "goal, not guarantees):\n"
    "- VET each candidate goal against FINER — Feasible, Interesting, Novel, "
    "Ethical, Relevant.\n"
    "- STRUCTURE scope with PICO/SPIDER-style components where they fit (who/what "
    "population, what intervention or exposure, what comparison, what outcome), so "
    "the boundaries of the inquiry are explicit.\n"
    "- Make SUCCESS CRITERIA SMART: specific, measurable, checkable sub-outcomes "
    "that mark progress — derived from the goal's components.\n"
    "- Make the goal SHARP and SCOPED; avoid an overly broad objective.\n"
    "- Orient it toward surfacing NON-OBVIOUS, under-cross-referenced CONNECTIONS "
    "between sources/ideas — not restating what a plain search already shows.\n"
    "- Frame HONESTLY: 'surface and flag candidate connections that appear "
    "non-obvious/under-cross-referenced', NEVER 'discover proven new truth' "
    "(absence of a prior link is not proof of novelty).\n"
    "- Optimize for verifiable, non-obvious connections, NOT volume of data."
)

# Coverage ratios -> honest qualitative proximity (no fabricated percentages).
_SUBSTANTIAL, _PARTIAL = 0.66, 0.33


@dataclass
class CandidateGoal:
    goal: str                    # the sharp objective statement
    rationale: str               # why this goal fits the subject
    would_yield: str             # what non-obvious connection it would surface
    success_criteria: list = field(default_factory=list)


@dataclass
class Objective:
    subject: str
    goal: str
    rationale: str = ""
    connection_focus: str = ""   # the kind of under-cross-referenced link to hunt
    success_criteria: list = field(default_factory=list)


@dataclass
class GoalProgress:
    proximity: str               # 'limited' | 'partial' | 'substantial' (NO fake %)
    covered: list = field(default_factory=list)   # criteria with well-supported findings
    open: list = field(default_factory=list)      # criteria still unmet
    plateauing: bool = False     # diminishing returns -> checkpoint the user
    summary: str = ""


def suggest_goals(subject: str, n: int = 3) -> list:
    """Propose n candidate objectives for a raw subject (Luna: suggest, don't force).
    Each is oriented to connection-finding and honestly framed (Elara/Vera)."""
    prompt = (
        f"A user wants Seeker to research this subject:\n\"{subject}\"\n\n"
        f"{_DOCTRINE}\n\n"
        f"Propose {n} distinct candidate research GOALS. For each, give the goal "
        "statement, a one-line rationale, what non-obvious CONNECTION it would "
        "surface, and 2-4 concrete success criteria. Optimize for verifiable, "
        "non-obvious connections, NOT volume of data.\n"
        'Return STRICT JSON {"goals": [{"goal": "...", "rationale": "...", '
        '"would_yield": "...", "success_criteria": ["..."]}]}.')
    data = _cheap_json(prompt)
    out = []
    for g in data.get("goals", []):
        if not isinstance(g, dict) or not g.get("goal"):
            continue
        out.append(CandidateGoal(
            goal=str(g.get("goal", "")).strip(),
            rationale=str(g.get("rationale", "")).strip(),
            would_yield=str(g.get("would_yield", "")).strip(),
            success_criteria=[str(c).strip() for c in g.get("success_criteria", [])
                              if str(c).strip()]))
    return out[:n]


def objective_from_choice(subject: str, chosen: CandidateGoal) -> Objective:
    """Freeze a user-chosen (or edited) candidate into the anchoring Objective."""
    return Objective(subject=subject, goal=chosen.goal, rationale=chosen.rationale,
                     connection_focus=chosen.would_yield,
                     success_criteria=list(chosen.success_criteria))


def estimate_progress(objective: Objective, mm, *, branch_id: str = "main",
                      prev: "GoalProgress | None" = None) -> GoalProgress:
    """Honest, mechanical proximity to the goal: for each success criterion, is there
    a WELL-SUPPORTED finding on the map addressing it? Qualitative proximity + the
    still-open criteria — never a fabricated percentage. `plateauing` compares to the
    prior estimate so the loop can CHECKPOINT the user instead of researching forever.
    """
    covered, still_open = [], []
    for crit in objective.success_criteria or []:
        hits = mm.query(crit, branch_id=branch_id, top_k=3, node_kind="finding",
                        hybrid=True)
        best = max(hits, key=lambda h: h.get("score", 0)) if hits else None
        tier = best.get("confidence_tier", "Speculative") if best else "Speculative"
        if best and standard_label(tier) == "well-supported" and best.get("score", 0) >= 0.4:
            covered.append(crit)
        else:
            still_open.append(crit)

    total = len(objective.success_criteria) or 1
    ratio = len(covered) / total
    proximity = ("substantial" if ratio >= _SUBSTANTIAL
                 else "partial" if ratio >= _PARTIAL else "limited")
    # plateau: coverage didn't grow since the last check -> diminishing returns
    plateauing = bool(prev and len(covered) <= len(prev.covered))
    summary = (f"{len(covered)}/{total} goal criteria now well-supported "
               f"({proximity}). {len(still_open)} still open.")
    return GoalProgress(proximity=proximity, covered=covered, open=still_open,
                        plateauing=plateauing, summary=summary)


def should_checkpoint_user(progress: GoalProgress) -> bool:
    """Ask the user 'is this sufficient?' when the goal isn't fully met AND progress
    has plateaued — the anti-infinite-research valve (Gambit's requirement)."""
    return bool(progress.open) and progress.plateauing
