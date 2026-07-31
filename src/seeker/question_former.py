"""Question-Former (Gambit, 2026-07-22) — the front door finally gets the trained questioner.

THE GAP THIS CLOSES. Every organ downstream generates questions (case plan, the Mind, interrogation),
but NOTHING formed the ROOT question — it was raw human input, unexamined. The v8 run proved the cost:
the topic string (typed by hand) said "the missing and dead American scientists" and lumped Amy
Eskridge under "missing" when she died in 2022 — a factual error baked into the foundation, poisoning
every lead built from it. Gambit: "we are asking the wrong question... what system is generating the
question?" Answer: none was. Now one does.

HOW (panel + doctrine + fact-check):
  1. FACT-SANITY — one grounded Perplexity Sonar call establishes the basic facts (who, what happened,
     statuses) so the question can't misstate a person's fate. Grounded search, not model memory (Vera).
  2. PANEL — 2-3 DIFFERENT models draft the investigation question independently under the Mind's
     ratified brief-17 doctrine (imported, not duplicated — Cipher). Different labs so one model's
     sloppiness can't survive (Noor: 'missing and dead' was a single-writer error).
  3. JUDGE — the reasoning model merges the drafts against the doctrine + facts and returns the final
     question WITH its corrections listed, so a fix like 'Eskridge is deceased, not missing' is
     visible, never silent (Vera).

Runs ONCE per investigation (~5 cheap calls, Marcus). Off-switch: SEEKER_FORM_QUESTION=0.
Fail-open: any error returns the raw topic unchanged — forming a question must never block a run.
Ghost: the formed question stays NEUTRAL — establish fates and test alleged connections; never
presume foul play or anyone's guilt.
"""
from __future__ import annotations

import os

from . import config
from .memory.gap_detector import _cheap_json, _reason_json
from .mind.mind import _DOCTRINE   # the council-ratified brief-17 questioning doctrine — one source

# Different labs on purpose: the panel exists to kill single-model blind spots.
PANEL_MODELS = ["anthropic/claude-sonnet-4.5", "openai/gpt-4.1", "google/gemini-2.5-flash"]


def _grounded_facts(topic: str, entities: list) -> str:
    """One grounded Perplexity call: the basic facts the question must not contradict.
    Returns a short factual brief ('' on failure — the judge then leans on the panel only)."""
    try:
        import requests
        names = ", ".join(entities[:10]) if entities else ""
        q = (f"Briefly state the verified basic facts about: {topic}. "
             + (f"For each of these people state their documented status (missing / deceased / "
                f"alive / unknown) with dates if known: {names}. " if names else "")
             + "Facts only, no speculation, cite nothing unverified as fact.")
        r = requests.post("https://api.perplexity.ai/chat/completions",
                          headers={"Authorization": f"Bearer {config.PERPLEXITY_API_KEY}",
                                   "Content-Type": "application/json"},
                          json={"model": config.PERPLEXITY_RECON_MODEL,
                                "messages": [{"role": "user", "content": q}]},
                          timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "")[:2500]
    except Exception:
        return ""


def _draft(topic: str, facts: str, model: str) -> str:
    """One panel member drafts the investigation question under the doctrine. '' on failure."""
    try:
        data = _cheap_json(
            "You are forming the ROOT QUESTION for a serious investigation engine. Given the raw "
            "TOPIC and the GROUNDED FACTS, write the single best investigation question.\n"
            f"Follow this questioning doctrine strictly:\n{_DOCTRINE}\n"
            "Additional hard rules: COVER EVERY person provided — never omit a name; if a person's status is "
            "not corroborated by the facts, keep them with 'status unconfirmed' (an unverified person gets "
            "investigated HARDER, not dropped). State each person's fate ACCURATELY per the facts (never "
            "call a deceased person missing); NEUTRAL framing — establish what happened and test alleged "
            "connections, never presume foul play, a pattern, or anyone's guilt; concrete and "
            "answerable, not grandiose ('how close can we get to solving the mystery' is BAD — "
            "'establish each person's documented fate and test each alleged connection against "
            "primary sources' is GOOD).\n\n"
            f"TOPIC (raw): {topic}\n\nGROUNDED FACTS:\n{facts or '(unavailable)'}\n\n"
            'Return STRICT JSON: {"question": "..."}', model=model)
        return str((data or {}).get("question", "")).strip()
    except Exception:
        return ""


def form_question(topic: str, *, entities: list | None = None) -> dict:
    """Form the root investigation question: grounded facts -> independent panel drafts -> judge.
    Returns {"question": str, "corrections": [str], "drafts": [str], "facts_used": bool}.
    Fail-open: on any failure question == topic (raw, unchanged)."""
    topic = " ".join((topic or "").split())
    out = {"question": topic, "corrections": [], "drafts": [], "facts_used": False}
    if not topic or os.environ.get("SEEKER_FORM_QUESTION", "1") == "0":
        return out
    try:
        ents = [str(e).strip() for e in (entities or []) if str(e).strip()]
        facts = _grounded_facts(topic, ents)
        out["facts_used"] = bool(facts)
        drafts = []
        for m in PANEL_MODELS:
            d = _draft(topic, facts, m)
            if d:
                drafts.append(d)
        out["drafts"] = drafts
        if not drafts:
            return out
        dblob = "\n".join(f"{i+1}. {d}" for i, d in enumerate(drafts))
        judged = _reason_json(
            "You are the judge for an investigation engine's ROOT QUESTION. Three models drafted "
            "candidates from the same topic and grounded facts. Produce the FINAL question: take the "
            "best draft or merge them; it must satisfy the doctrine, match the facts exactly (a "
            "deceased person is 'deceased', never 'missing'), COVER EVERY person from the topic/roster — a "
            "name may never be omitted; uncorroborated status reads 'status unconfirmed' — stay NEUTRAL "
            "(no presumed foul play or guilt), and be concrete/answerable. Also list CORRECTIONS — every factual or framing "
            "error in the RAW TOPIC that the final question fixes (e.g. 'topic called Eskridge "
            "missing; she died June 2022'). If the raw topic was already correct, corrections=[].\n"
            f"Doctrine:\n{_DOCTRINE}\n\nRAW TOPIC: {topic}\n\n"
            f"GROUNDED FACTS:\n{facts or '(unavailable)'}\n\nDRAFTS:\n{dblob}\n\n"
            'Return STRICT JSON: {"question": "...", "corrections": ["..."]}')
        if isinstance(judged, dict) and str(judged.get("question", "")).strip():
            q = str(judged["question"]).strip()
            # VERIFY, DON'T TRUST THE SELF-REPORT (2026-07-27): v14's judge listed "ensured that each
            # named person is included by name" among its corrections — and had silently dropped 3 of
            # 13 (Sullivan, Eskridge, LeBlanc). A component claiming compliance is not compliance.
            # Check every seeded name is actually present; append the omitted ones rather than
            # re-prompting (cheaper, and guarantees the roster survives).
            omitted = [n for n in ents if n.split()[-1].lower() not in q.lower()]
            if omitted:
                q = q.rstrip("? ") + f"? Also establish the documented status and cause for: {', '.join(omitted)}."
                out["corrections"].append(
                    f"AUTO-REPAIR: the formed question omitted {len(omitted)} roster name(s) "
                    f"({', '.join(omitted)}) despite the never-omit rule; appended.")
            out["question"] = q
            out["corrections"] += [str(c).strip() for c in (judged.get("corrections") or [])][:8]
        return out
    except Exception:
        return out
