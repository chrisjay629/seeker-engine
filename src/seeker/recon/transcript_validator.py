"""Transcript validation gates (brief 01 — Recon owns the YouTube channel).

The YouTube channel's single point of failure: `youtube-transcript-api` can
return empty or partial transcripts silently when YouTube changes internals, so
garbage findings enter the map with no alert (Transfer Blueprint v2 §5a). These
gates run BEFORE a node is created and make degradation visible.

Three gates, in order:
  1. health_check     — empty / degenerate transcript -> DROP (nothing to extract).
  2. wordcount_ratio  — words vs. video duration (~150 wpm baseline, Felix).
                        A FLAG, not a hard drop (Felix/Vera): speaking rate varies
                        and legitimately collapses for coding screencasts, demos,
                        music. It logs a suspicion; the relevance gate decides.
  3. relevance_ok     — cheap Groq yes/no: does this transcript actually bear on
                        the topic? -> DROP if no.

Spine (Vera/Elara): the relevance gate judges EXTERNAL transcript content against
the search topic — it never grades Seeker's own output, so it is an external
filter (like the pre-filter), not self-grading. Every result is logged so the
gate's false-negative rate is auditable over time.

Failure policy (Ghost/Ray): the relevance gate FAILS OPEN on infra error — a Groq
outage must NOT silently delete knowledge (that is the exact silent-zero failure
we are fixing). An errored gate keeps the transcript and logs the error distinctly
so an outage never masquerades as "irrelevant".
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Optional

import requests

from .. import config

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

WORDS_PER_MINUTE = 150          # Felix's baseline for expected transcript length
MIN_HEALTHY_WORDS = 100         # absolute floor: no substantive video transcript is
#                                 under this (Gambit) — under it = broken/partial fetch
DROP_RATIO = 0.35               # words < 35% of duration-predicted -> broken -> DROP
FLAG_RATIO = 0.50               # 35-50% -> gray zone -> FLAG but keep (Felix: sparse
#                                 speech in demos / screencasts / music is still valid)

_LOG_PATH = os.path.join("runs", "transcript_validation_log.jsonl")


@dataclass
class ValidationResult:
    passed: bool
    reasons: list = field(default_factory=list)   # why it was dropped / flagged
    n_words: int = 0
    wordcount_ratio: Optional[float] = None        # None if duration unknown
    wordcount_suspect: bool = False
    relevance: Optional[str] = None                # "yes" | "no" | "gate_error" | None
    url: str = ""
    topic: str = ""


# --- individual gates (pure, testable) ---

def word_count(transcript: Optional[str]) -> int:
    return len((transcript or "").split())


def health_check(transcript: Optional[str]) -> bool:
    """False when the transcript is empty or degenerate (nothing to extract)."""
    return word_count(transcript) >= MIN_HEALTHY_WORDS


def wordcount_ratio(transcript: Optional[str],
                    duration_seconds: Optional[float]) -> Optional[float]:
    """actual_words / expected_words (150 wpm). None if duration is unknown."""
    if not duration_seconds or duration_seconds <= 0:
        return None
    expected = (duration_seconds / 60.0) * WORDS_PER_MINUTE
    if expected <= 0:
        return None
    return round(word_count(transcript) / expected, 3)


def is_wordcount_suspect(transcript: Optional[str],
                         duration_seconds: Optional[float],
                         low_ratio: float = FLAG_RATIO) -> bool:
    """True = fewer words than the duration predicts (gray zone). A FLAG, not a
    drop. (validate_transcript inlines this now; kept for direct/testing use.)"""
    ratio = wordcount_ratio(transcript, duration_seconds)
    return ratio is not None and ratio < low_ratio


def relevance_ok(text: str, topic: str) -> str:
    """Cheap Groq yes/no on EXTERNAL content. Returns 'yes' | 'no' | 'gate_error'.

    Fails OPEN: on any infra error returns 'gate_error' (caller keeps the node),
    so a Groq outage never masquerades as irrelevance."""
    prompt = (
        f"Topic: {topic}\n\nDoes the following transcript contain information "
        f"relevant to that topic? Answer with only one word: yes or no.\n\n"
        f"TRANSCRIPT:\n{(text or '')[:6000]}")
    try:
        resp = requests.post(
            _GROQ_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.GROQ_RECON_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0, "max_tokens": 4},
            timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        ans = resp.json()["choices"][0]["message"]["content"].strip().lower()
        return "yes" if ans.startswith("y") else "no"
    except Exception:
        return "gate_error"


# --- assembled pipeline ---

def validate_transcript(transcript: Optional[str], topic: str, *,
                        duration_seconds: Optional[float] = None,
                        url: str = "", log: bool = True) -> ValidationResult:
    """Run the three gates. Drops on empty or clearly-irrelevant; flags (keeps)
    on low word-count or a gate error. Logs the result for the audit trail."""
    n = word_count(transcript)
    res = ValidationResult(passed=True, n_words=n, url=url, topic=topic)

    # gate 1 — absolute floor (math, free): no real video transcript is under 100
    # words. Under it = broken/partial fetch, drop it.
    if n < MIN_HEALTHY_WORDS:
        res.passed = False
        res.reasons.append("under_100_words")
        if log:
            _append_log(res)
        return res

    # gate 2 — duration match (math, free): compare words to what the video's own
    # timestamp length predicts (~150 wpm). Grossly short = broken/partial -> DROP.
    # Mildly short = sparse-but-valid (demo/screencast/music) -> FLAG, keep.
    res.wordcount_ratio = wordcount_ratio(transcript, duration_seconds)
    if res.wordcount_ratio is not None:
        if res.wordcount_ratio < DROP_RATIO:
            res.passed = False
            res.reasons.append("far_under_duration")
            if log:
                _append_log(res)
            return res
        if res.wordcount_ratio < FLAG_RATIO:
            res.wordcount_suspect = True
            res.reasons.append("wordcount_suspect")

    # gate 3 — relevance: the actual keep/drop decision (fails open)
    res.relevance = relevance_ok(transcript, topic)
    if res.relevance == "no":
        res.passed = False
        res.reasons.append("irrelevant")
    elif res.relevance == "gate_error":
        res.reasons.append("relevance_gate_error_kept")  # kept by fail-open

    if log:
        _append_log(res)
    return res


def _append_log(res: ValidationResult) -> None:
    """Append the result to runs/ (gitignored) — the auditable trail."""
    try:
        os.makedirs("runs", exist_ok=True)
        rec = asdict(res)
        rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(_LOG_PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass  # logging must never break ingestion
