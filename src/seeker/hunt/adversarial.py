"""Adversarial Agent — pre & post flight (brief 06).

Brackets the verification spine on BOTH ends. Before Seeker spends anything,
pre-flight challenges the question (mechanical pre-filter scores + source
credibility). After Seeker returns, post-flight challenges the answer: did it
connect to the map, did it open new gaps — checked MECHANICALLY (embedding
similarity), never by the model rating its own answer. Updates the Credibility
Ledger from the outcome. Standard calls only (cost discipline).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..memory.memory_map import MemoryMap
from ..memory.gap_detector import _cheap_json
from ..mind import prefilter
from . import credibility
from .fetch import domain_of

_PREFLIGHT_MIN = 0.20   # combined pre-filter score a question must clear
_CONNECT = 0.35         # similarity at which a finding "connects" to the map


@dataclass
class PreFlight:
    survived: bool
    scores: dict
    reason: str


@dataclass
class PostFlight:
    answered: bool                 # findings connect to the map / are on-topic
    n_findings: int
    n_connected: int
    new_domains_rewarded: list = field(default_factory=list)
    domains_penalized: list = field(default_factory=list)


def pre_flight(question: str, *, mm: MemoryMap | None = None,
               branch_id: str = "main") -> PreFlight:
    mm = mm or MemoryMap()
    scores = prefilter.score(question, mm=mm, branch_id=branch_id)
    survived = scores["combined"] >= _PREFLIGHT_MIN
    reason = ("clears pre-filter" if survived
              else f"combined {scores['combined']} < {_PREFLIGHT_MIN}")
    return PreFlight(survived=survived, scores=scores, reason=reason)


def contradicts_consensus(claim: str, *, mm: MemoryMap | None = None,
                          branch_id: str = "main", min_consensus: int = 3,
                          exclude_ids: set | None = None) -> dict:
    """Check whether `claim` contradicts a well-corroborated part of the map.
    Mechanical retrieval + an EXTERNAL stance judgment comparing the new claim
    against established consensus (not the model grading its own answer).
    `exclude_ids` drops the claim's own node so it can't corroborate itself."""
    mm = mm or MemoryMap()
    exclude_ids = exclude_ids or set()
    neighbors = mm.query(claim, branch_id=branch_id, top_k=min_consensus + 4,
                         node_kind="finding")
    consensus = [h for h in neighbors
                 if h["score"] >= _CONNECT and h["id"] not in exclude_ids
                 and h["text"].strip() != claim.strip()]
    if len(consensus) < min_consensus:
        return {"contradiction": False, "reason": "no strong consensus nearby"}

    listing = "\n".join(f"- {h['text']}" for h in consensus)
    data = _cheap_json(
        "A NEW claim is being checked against ESTABLISHED consensus from multiple "
        "independent sources. Does the new claim CONTRADICT the consensus on "
        "substance? Return STRICT JSON {\"contradicts\": true/false}.\n\n"
        f"NEW CLAIM:\n{claim}\n\nESTABLISHED CONSENSUS:\n{listing}")
    contra = bool(data.get("contradicts"))
    return {"contradiction": contra, "consensus_size": len(consensus),
            "reason": "contradicts multi-source consensus" if contra
                      else "consistent with consensus"}


def post_flight(question: str, findings: list, *, mm: MemoryMap | None = None,
                branch_id: str = "main") -> PostFlight:
    mm = mm or MemoryMap()
    connected = 0
    by_domain: dict = {}
    for f in findings:
        # does this finding connect to what the map already holds? (mechanical)
        hits = mm.query(f.claim, branch_id=branch_id, top_k=1, node_kind="finding")
        top = max((h["score"] for h in hits), default=0.0)
        if top >= _CONNECT:
            connected += 1
        for c in f.citations:
            d = domain_of(getattr(c, "url", ""))
            if d:
                by_domain.setdefault(d, 0)
                by_domain[d] += 1

    rewarded, penalized = [], []
    for d, n in by_domain.items():
        if n > 0:
            rewarded.append((d, credibility.reward(d)))
    return PostFlight(answered=len(findings) > 0, n_findings=len(findings),
                      n_connected=connected, new_domains_rewarded=rewarded,
                      domains_penalized=penalized)
