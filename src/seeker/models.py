"""Seeker data contract — the shapes that move between components.

Mirrors 04-Task-Briefs/00-shared-context.md §2. Fields marked "isolation"
(branch_id, rate_limit_bucket) exist on every record from day one so the
Phase 2 introspective branch can never bleed into the live investigation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# Confidence tiers — how much external evidence a finding has, never whether
# it may be questioned. Tiers move as evidence changes.
TIERS = ("Accepted", "Moderately Accepted", "Controversial", "Speculative")

SourceType = str  # "llm" | "web" | "youtube" | "perplexity"


@dataclass
class Citation:
    url: str
    title: str = ""
    source_type: SourceType = "web"
    retrieved_at: str = field(default_factory=_now)
    quote: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourceResponse:
    """One independent voice's answer to the Recon question. Kept SEPARATE —
    never merged. Disagreement between responses is the product."""
    question_id: str
    source_type: SourceType
    source_label: str            # e.g. "anthropic/claude-opus-4.7", "youtube:<id>"
    raw_text: str
    citations: list = field(default_factory=list)         # list[Citation]
    error: Optional[str] = None                            # set if this source failed
    retrieved_at: str = field(default_factory=_now)
    id: str = field(default_factory=lambda: _id("src"))
    # isolation
    branch_id: str = "main"
    rate_limit_bucket: str = "main"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["citations"] = [c.to_dict() if isinstance(c, Citation) else c
                          for c in self.citations]
        return d

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.raw_text.strip())


@dataclass
class Finding:
    """One atomic claim extracted from source(s). A lit node on the Memory Map."""
    claim: str
    source_ids: list = field(default_factory=list)
    citations: list = field(default_factory=list)
    confidence_tier: str = "Speculative"
    embedding_ref: Optional[str] = None
    node_kind: str = "finding"
    id: str = field(default_factory=lambda: _id("find"))
    created_at: str = field(default_factory=_now)
    branch_id: str = "main"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["citations"] = [c.to_dict() if isinstance(c, Citation) else c
                          for c in self.citations]
        return d


@dataclass
class GapNode:
    """A hole or a disagreement. A dim node on the Memory Map. Emitted by the
    Gap Detector (brief 03) via mechanical detection — never a model grading."""
    question: str
    gap_type: str = "dim"        # "disagreement" | "dim" | "unknown"
    involved_source_ids: list = field(default_factory=list)
    disagreement_score: float = 0.0
    status: str = "dim"          # "dim" (unfilled) | "lit" (answered)
    embedding_ref: Optional[str] = None
    node_kind: str = "gap"
    id: str = field(default_factory=lambda: _id("gap"))
    created_at: str = field(default_factory=_now)
    branch_id: str = "main"

    def to_dict(self) -> dict:
        return asdict(self)
