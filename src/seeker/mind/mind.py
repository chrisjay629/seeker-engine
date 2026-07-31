"""The Mind (brief 05) — the only part that thinks.

Reads the Memory Map, generates a RANKED next-question list, applies the
mechanical pre-filter, logs to the Question Ledger. Uses Claude via OpenRouter
with reasoning tokens (Extended-Thinking equivalent; no native Anthropic key
yet). Council Lite (Marcus/Vera/Ray/Zara) is simulated inside the reasoning
prompt with strict triggers.

Spine: the Mind generates questions and judgments — it NEVER grades its own
answer quality or declares an investigation complete. It must not propose any
question that asks the system to rate itself.
"""
from __future__ import annotations

import json
import os

import requests

from .. import config
from ..memory.memory_map import MemoryMap
from . import prefilter, question_ledger as ledger

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Routed to the REASONING tier (2026-07-21): question generation is verdict-class work, but Opus 4.6
# was ~15x the price and was already pulled from recon for cost. MIND_MODEL env still overrides.
_MIND_MODEL = os.environ.get("MIND_MODEL", "") or config.REASONING_MODEL

_COUNCIL_LITE = (
    "Before finalizing, run each question past Council Lite:\n"
    "- Marcus (structure/cost): is it one clean, well-scoped question?\n"
    "- Vera (verification spine): REJECT any question that would make the system "
    "grade its own quality or confirm its own answer. Verification comes from outside.\n"
    "- Ray (shippable): can Seeker actually answer this now with real sources?\n"
    "- Zara (elegance): is there a simpler question that collapses several?\n"
)

# Master-questioning doctrine (brief 17), codified from brain `questioning-tradecraft`
# and council-ratified. Grounded in Heuer's ACH + cognitive-interview funneling +
# the neutral-vs-leading-question literature. Kept tight (Marcus: bounded token cost).
_DOCTRINE = (
    "Follow master-investigator questioning doctrine:\n"
    "1. DECOMPOSE the objective (timeline, actors, mechanism, primary sources, "
    "counter-evidence); funnel from general to specific.\n"
    "2. For the leading explanation on the map, include >=1 question that would "
    "DISPROVE it, not confirm it (Analysis of Competing Hypotheses).\n"
    "3. Include >=1 SOURCE-DIRECTED question — who reported it, when, in what "
    "document (can it be proven, and by what evidence?).\n"
    "4. NEUTRAL framing only — reject any question that presupposes its answer "
    "(no 'he was wearing red, wasn't he?' leading forms).\n"
    "5. Anchor every question to the OBJECTIVE below; if new questions would only "
    "restate what the map already holds, return fewer and signal saturation.\n"
)

_PROMPT = """You are the Mind of a persistent AI investigation engine. You read a \
spatial Memory Map of what is known and generate the next questions to pursue.

OBJECTIVE (the goal this whole investigation serves — anchor every question to it):
{objective}

INVESTIGATION QUESTION:
{question}

WHAT THE MAP ALREADY HOLDS (lit findings):
{findings}

OPEN GAPS (dim nodes / disagreements):
{gaps}

{doctrine}
Generate {n} candidate NEXT questions that push toward the frontier — the edges \
of what the map does not yet contain. Favor questions that target disagreement, \
open genuinely new territory, or are load-bearing for the whole investigation.

{rules}

{council}

Return STRICT JSON: {{"questions": [{{"q": "...", "why": "one line"}}]}}
Do NOT propose questions that ask the system to evaluate its own performance."""


def _parse_json(content: str) -> dict:
    """Reasoning-enabled Claude often wraps JSON in a ```json fence — strip it."""
    s = content.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    if "{" in s:  # fall back to the outermost braces
        s = s[s.index("{"): s.rindex("}") + 1]
    return json.loads(s)


def _reasoned_json(prompt: str) -> dict:
    """Claude via OpenRouter with reasoning tokens enabled (Extended Thinking)."""
    try:
        r = requests.post(
            _OPENROUTER_URL,
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": _MIND_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "reasoning": {"max_tokens": 4000},
                  # cap the answer so providers don't PRE-RESERVE the model's full
                  # 65k output ceiling (which blocks the call when credit is tight).
                  # 4000 reasoning + a small JSON of questions fits easily in 8000.
                  "max_tokens": 8000,
                  "response_format": {"type": "json_object"}},
            timeout=180)
        r.raise_for_status()
        return _parse_json(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        return {"_error": repr(e)}


def _summarize(hits: list, limit: int = 12) -> str:
    if not hits:
        return "(none yet)"
    return "\n".join(f"- {h['text'][:110]}" for h in hits[:limit])


def _question_rules() -> str:
    """The shared question-shape rules (interrogate._QUESTION_RULES). The Mind SEES the findings but
    its prompt never constrained the FORM, so it still produced 35-word document-existence
    interrogatories in v14 — seeing the evidence is necessary, not sufficient."""
    try:
        from ..interrogate import _QUESTION_RULES
        return _QUESTION_RULES
    except Exception:
        return ""


def generate_next_questions(question: str, *, branch_id: str = "main",
                            n: int = 5, cycle_n: int = 0, objective: str = "") -> list:
    mm = MemoryMap()
    # hybrid retrieval (vector + BM25) — measured to sharpen exact-fact terrain
    # reading without hurting semantics (build-log 2026-07-08)
    findings = mm.query(question, branch_id=branch_id, top_k=12, node_kind="finding", hybrid=True)
    gaps = mm.query(question, branch_id=branch_id, top_k=6, node_kind="gap", hybrid=True)

    prompt = (_PROMPT
              .replace("{objective}", objective.strip() or "(none set — treat the "
                       "investigation question as the objective)")
              .replace("{question}", question)
              .replace("{findings}", _summarize(findings))
              .replace("{gaps}", _summarize(gaps))
              .replace("{doctrine}", _DOCTRINE)
              .replace("{rules}", _question_rules())
              .replace("{council}", _COUNCIL_LITE)
              .replace("{n}", str(n)))
    data = _reasoned_json(prompt)
    candidates = data.get("questions", []) if isinstance(data, dict) else []

    ranked = []
    for c in candidates:
        q = (c.get("q") or "").strip() if isinstance(c, dict) else ""
        if not q or ledger.seen(q, branch_id):
            continue
        s = prefilter.score(q, mm=mm, branch_id=branch_id)
        ranked.append({"q": q, "why": c.get("why", ""), "scores": s})

    ranked.sort(key=lambda x: x["scores"]["combined"], reverse=True)
    for r in ranked:
        ledger.log(r["q"], branch_id=branch_id, cycle_n=cycle_n,
                   scores=r["scores"], outcome="proposed")
    return ranked
