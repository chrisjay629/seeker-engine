"""Interrogation — the questioning LOOP (Gambit, 2026-07-21). The differentiator, finally mechanical.

THE GAP THIS CLOSES. Seeker asked ~10 questions for a whole case (one templated question per person),
translated them per engine, ran ONE small wave-2, and then — the crucial failure — drew its
connections and immediately wrote the report. A real investigator does the opposite: asks DEEP about
each subject, reads, and then interrogates every CONNECTION for the questions it raises ("Reza and
McCasland both tie to AFRL — did their time overlap? which program? who ran it?"). The owner's most
repeated late-project complaint: "when all the data is in nodes and overlooked for connections, MORE
questions should be asked — I don't feel like it's doing half of that." He was right; it wasn't.

This module is two generators the director loops over:
  1. question_bank(subject, entity)      — a real investigator's interrogation set for ONE person
     (career/what they studied/how they went missing/claims before death/interviews/who they knew).
  2. questions_from_connections(...)      — every surfaced link AND verified non-connection becomes a
     checkable follow-up question, so a connection is a LEAD to chase, not a finished result.

Guardrails (council):
  • Ghost: a connection-question is a NEUTRAL probe, never an accusation. "Did X and Y overlap on
    program Z / co-author / share an employer" — never "did X harm Y".
  • Vera: questions are probes; their answers are graded by the normal four-label rules.
  • Marcus: questions are pennies, FETCHES are dollars — the caller bounds how many get driven and how
    many rounds run. This module only generates; it never fetches.
Fail-open: any error returns [] so the loop simply doesn't deepen that round.
"""
from __future__ import annotations

from .memory.gap_detector import _reason_json

# Angles a real investigator works for a person of interest — the shape of the owner's "list 50".
_PERSON_ANGLES = (
    "career and specific projects/programs worked on",
    "what they studied, invented, or published",
    "how they went missing or died — the documented record",
    "what they said publicly before the event (interviews, posts, claims)",
    "whether they expressed fear, threats, or being watched",
    "who they worked with, for, and knew (colleagues, supervisors, co-authors)",
    "official response and case status",
)


def evidence_for(subject: str, entity: str, *, branch_id: str = "main", mm=None,
                 limit: int | None = None) -> list:
    """The findings we ALREADY have about one person — the context a question generator must read
    before it can ask anything specific. Reuses the profiles' retrieval + name matcher (one canonical
    lookup, no second copy to drift — Zara). Returns claim strings; [] on any failure."""
    try:
        from . import synthesis as _syn
        from .entity_profiles import _entity_keys
        buckets = _syn.gather_findings(subject, branch_id=branch_id, mm=mm)
        rows = []
        for label in ("well-supported", "contested", "unverified"):
            rows += buckets.get(label, [])
        keys = _entity_keys(entity)
        # limit=None (2026-07-30): EVERY finding about this person. This capped at 14, so the
        # question generator saw 14 of McCasland's 68 — and the specificity of a question is bounded
        # by what its author can see. This organ's blindness was already diagnosed once as the root
        # cause of bad questions; it was given sight and then handed a keyhole.
        got = [c for c in ((f.get("claim", "") or "") for f in rows)
               if any(k in c.lower() for k in keys)]
        return got if limit is None else got[:limit]
    except Exception:
        return []


# The rules that separate an investigator's question from a FOIA request. Measured on the v14 run:
# 75% of generated questions asked whether a DOCUMENT EXISTS instead of what happened, 95% ran over
# 28 words, 67% were compound. Those are research-task descriptions, not questions anyone can search.
_QUESTION_RULES = (
    "HOW TO WRITE THE QUESTIONS — these rules matter more than coverage:\n"
    "- UNDER 12 WORDS each. Short. 'Who found Carl Grillmair's body?' not a paragraph.\n"
    "- ONE question per entry. Never join two with 'and' or a dash.\n"
    "- Ask WHAT HAPPENED, never whether a record exists. BANNED openings: 'Is there any...', "
    "'Are there any...', 'Has any...', 'Have any...', 'What primary source documents...', "
    "'What documentation establishes...'. Primary sourcing is the standard the ANSWER must meet — "
    "it is NEVER what the question asks about.\n"
    "- Each question must name something SPECIFIC from the evidence — a person, place, date, "
    "document, employer, or vehicle. A question that would fit any case is a wasted question.\n"
    "- Write what a detective would type into a search box.\n"
    "GOOD: 'Who reported Monica Reza missing?' · 'What did Grillmair's autopsy conclude?' · "
    "'Which program did McCasland and Reza share?' · 'Was there a note in Eskridge's car?'\n"
    "BAD: 'What primary-source documents explicitly confirm the verified status and documented "
    "circumstances for Monica Jacinto Reza?' (asks about paperwork, 19 words, unsearchable)\n")


def question_bank(subject: str, entity: str, *, goal: str = "", n: int = 6,
                  branch_id: str = "main", mm=None) -> list:
    """A per-person interrogation set — the deep questions a real investigator would work for ONE
    subject, in plain searchable register. Returns short question strings. Fail-open to [].

    EVIDENCE-FED (2026-07-27, the root-cause fix): this generator used to receive only the subject
    string and a NAME — it was asking questions about a case it had never read, so all it could
    produce were generic document-shaped questions ('what is the documented record of how this person
    died'). Given the person's ACTUAL findings it asks what an investigator asks — about the text she
    sent, the SUV outside, the named report to Congress. Same model, one variable changed."""
    entity = " ".join((entity or "").split())
    if not entity:
        return []
    try:
        angles = "; ".join(_PERSON_ANGLES)
        ev = evidence_for(subject, entity, branch_id=branch_id, mm=mm)
        ev_block = ("\n".join(f"- {c[:220]}" for c in ev) if ev
                    else "(nothing gathered on this person yet — ask the basic opening questions a "
                         "detective starts with: who reported it, when and where last seen, what the "
                         "official record says)")
        prompt = (
            "You are a lead investigator building the question list for ONE person in a case. Below "
            "is what your team has ALREADY established about them. Read it, then write the questions "
            "you would chase NEXT — the specific unanswered things a detective would go after.\n\n"
            f"{_QUESTION_RULES}\n"
            f"Work these angles where the evidence gives you a hook: {angles}.\n"
            "Neutral probes only: employment, timeline, statements, relationships — NEVER presume or "
            "ask whether they committed or suffered a crime, and never name a suspect.\n\n"
            f"CASE: {subject}\n" + (f"GOAL: {goal}\n" if goal else "") +
            f"PERSON: {entity}\n\n"
            f"WHAT WE ALREADY KNOW ABOUT {entity}:\n{ev_block}\n\n"
            f'Return STRICT JSON: {{"questions": ["...", "..."]}} with {n} questions about {entity}. '
            "Each under 12 words, each naming something specific.")
        data = _reason_json(prompt)
        out = []
        for q in (data.get("questions") or []) if isinstance(data, dict) else []:
            s = " ".join(str(q).strip().strip('"').split())
            if s and s.lower() not in {o.lower() for o in out}:
                out.append(s)
        return out[:n]
    except Exception:
        return []


def follow_ups(subject: str, question: str, claims: list, *, n: int = 2,
               already_asked: set | None = None) -> list:
    """THE FOLLOW-UP HOP (Gambit, 2026-07-27) — the loop the app never had.

    Seeker asked a question, fetched the answer, and moved on. Nothing ever read an ANSWER and asked
    what IT raised. So the v14 A/B surfaced 'Reza was last seen waving to a companion ~30 feet away'
    and 'Chavez left on foot on 37th Street' — and then dropped both threads on the floor. A real
    investigator does the opposite: every answer is a door.

    This takes ONE question and the claims it actually returned, and asks what a detective would
    chase next. Not a new organ — the same evidence-fed prompt shape as question_bank, pointed at a
    single answer instead of a whole corpus (Gambit: 'not every feature needs to be built out —
    maybe it's prompts to LLMs with set instructions').

    `already_asked` (lowercased) suppresses rephrasings of anything the run has asked before —
    without it the loop happily re-asks its own parent (Noor). Returns [] on any failure."""
    claims = [str(c).strip() for c in (claims or []) if str(c).strip()]
    if not question or not claims:
        return []
    try:
        ev = "\n".join(f"- {c[:240]}" for c in claims[:10])
        prompt = (
            "You are a lead investigator. You asked ONE question and got the answer below. A good "
            "investigator treats every answer as a door: a name you did not have, a time, a place, a "
            "witness, an object. Write the question(s) you would chase NEXT because of THIS answer.\n\n"
            f"{_QUESTION_RULES}\n"
            "CRITICAL: do NOT rephrase the question you already asked, and do not ask something the "
            "answer already states. Each follow-up must go one step FURTHER — pull on a specific "
            "detail that just appeared. If the answer genuinely opens nothing new, return an empty "
            "list; that is a valid and useful outcome.\n"
            "Example — Q: 'Who last saw Reza on June 22?' A: '...waving to a companion 30 feet away.'\n"
            "  GOOD follow-up: 'Who was the companion hiking near Reza that morning?'\n"
            "  BAD follow-up: 'Who last saw Monica Reza?' (rephrases the parent)\n"
            "Neutral probes only — never presume a crime or name a suspect.\n\n"
            f"CASE: {subject}\n\nQUESTION ASKED: {question}\n\nWHAT CAME BACK:\n{ev}\n\n"
            f'Return STRICT JSON: {{"questions": ["..."]}} with AT MOST {n} follow-ups, each under '
            "12 words. Return an empty list if the answer opens nothing new.")
        data = _reason_json(prompt)
        seen = {s.lower() for s in (already_asked or set())} | {question.lower()}
        out = []
        for q in (data.get("questions") or []) if isinstance(data, dict) else []:
            s = " ".join(str(q).strip().strip('"').split())
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
        return out[:n]
    except Exception:
        return []


def questions_from_connections(subject: str, connections: dict, *, n: int = 6) -> list:
    """Turn the Connections Engine's output into the NEXT questions — the loop the app was missing.
    Each real link and each verified non-connection raises a checkable follow-up. Returns question
    strings (neutral probes). Fail-open to []."""
    conns = (connections or {}).get("connections", []) or []
    nonconns = (connections or {}).get("non_connections", []) or []
    if not conns and not nonconns:
        return []
    try:
        link_txt = "\n".join(f"- LINK: {', '.join(c.get('entities', []))} — {c.get('link','')}"
                             for c in conns[:12]) or "(none)"
        non_txt = "\n".join(f"- NON-LINK (checked, none found): {x}" for x in nonconns[:8]) or "(none)"
        prompt = (
            "You are a lead investigator. Below are CONNECTIONS and verified NON-CONNECTIONS your team "
            "derived between people in a case. Each one raises OBVIOUS next questions a real "
            "investigator would immediately chase. For each meaningful link, ask what would confirm, "
            "quantify, or explain it (did their dates overlap? which specific program/contract? who "
            "supervised both? did they co-author or co-file? is there evidence they communicated?). "
            "For a surprising NON-connection, ask what would still tie them together if anything.\n"
            f"{_QUESTION_RULES}"
            "RULES: short, concrete, SEARCHABLE questions with the real names. NEUTRAL probes about "
            "employment/timeline/collaboration/records ONLY — never ask whether one person harmed "
            "another. No boilerplate.\n\n"
            f"CASE: {subject}\n\nCONNECTIONS:\n{link_txt}\n\nNON-CONNECTIONS:\n{non_txt}\n\n"
            f'Return STRICT JSON: {{"questions": ["...", "..."]}} with up to {n} sharp follow-ups.')
        data = _reason_json(prompt)
        out = []
        for q in (data.get("questions") or []) if isinstance(data, dict) else []:
            s = " ".join(str(q).strip().strip('"').split())
            if s and s.lower() not in {o.lower() for o in out}:
                out.append(s)
        return out[:n]
    except Exception:
        return []
