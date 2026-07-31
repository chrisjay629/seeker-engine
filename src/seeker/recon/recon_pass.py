"""Recon Pass — the assembled component (brief 01).

Runs the multi-source parallel sweep and the YouTube channel for one broad
investigation question, and returns a ReconResult holding:
  - source_responses: one SEPARATE response per LLM/web voice (disagreement
    preserved for the Gap Detector, brief 03)
  - youtube_findings: atomic claims extracted from video transcripts

This component collects and preserves. It does NOT judge quality, merge voices,
or decide completeness (verification spine). Downstream owns that.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import _id
from . import sources, youtube


@dataclass
class ReconResult:
    question: str
    question_id: str
    branch_id: str
    source_responses: list = field(default_factory=list)   # list[SourceResponse]
    youtube_findings: list = field(default_factory=list)    # list[Finding]

    @property
    def ok_sources(self) -> list:
        return [r for r in self.source_responses if r.ok]

    @property
    def failed_sources(self) -> list:
        return [r for r in self.source_responses if not r.ok]

    def summary(self) -> str:
        return (f"Recon {self.question_id}: "
                f"{len(self.ok_sources)}/{len(self.source_responses)} sources ok, "
                f"{len(self.youtube_findings)} youtube findings, "
                f"branch={self.branch_id}")


def run_recon(question: str, *, branch_id: str = "main",
              rate_limit_bucket: str = "main",
              youtube_results: int = 5,
              with_youtube: bool = True) -> ReconResult:
    question_id = _id("q")
    responses = sources.sweep(question, question_id,
                              branch_id=branch_id,
                              rate_limit_bucket=rate_limit_bucket)
    yt_findings = []
    if with_youtube:
        yt_findings = youtube.youtube_channel(question,
                                              num_results=youtube_results,
                                              branch_id=branch_id)
    return ReconResult(question=question, question_id=question_id,
                       branch_id=branch_id,
                       source_responses=responses,
                       youtube_findings=yt_findings)
