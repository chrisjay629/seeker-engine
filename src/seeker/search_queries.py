"""Search-query adapter (Gambit, 2026-07-21) — speak the SEARCH ENGINE's language, not ours.

THE BUG THIS FIXES. Seeker was shipping its INTERNAL investigator instructions straight to search
APIs. A query inventory measured it: the web/primary lanes sent

    "Verify the identity, current status, and documented cause or outcome for this specific
     individual from primary/authoritative sources: Monica Jacinto Reza"

— 153 chars of which ~130 are scaffolding and ~20 are the thing we actually want. YouTube got a
231-char research question. An independent search-quality audit rated those BROKEN: YouTube returned
generic "how to run a background check" videos, Exa returned people-search spam (Spokeo/Whitepages),
and the H4 primary lane's "(peer-reviewed study, original paper...)" suffix made it hunt ACADEMIC
PAPERS about a missing person — returning the victims' own CVs instead of death records.

Meanwhile Gambit typed `amy eskridge cause of death` into Google and got the answer instantly.

THE FIX (Gambit's design): a real investigator searches NAME + ANGLE, in plain keyword register —
"Amy Eskridge updates", "Amy Eskridge how she died", "Amy Eskridge conspiracy", "Amy Eskridge
anti-gravity research", "Amy Eskridge interviews being followed". So we:
  1. STRIP the instruction scaffolding out of a lead (keep the payload: the entity/topic).
  2. FAN OUT a person into angle-specific queries (the standard investigative angles below).
  3. Ask the model what an expert would actually TYPE into this engine (novel/non-person cases).
  4. Format per ENGINE: YouTube/Podcast are lexical (short keyword titles); web/Exa is neural
     (prose tolerated, but entity+place+date still wins).

Guardrails: queries only change WHAT WE ASK — every finding still goes through the same extraction,
grading, and confidence rules (Vera). Angles are neutral probes, not conclusions: asking "X
conspiracy" surfaces the claim so it can be ADJUDICATED, it never asserts one (Ghost).
"""
from __future__ import annotations

import re

# The angles a real investigator (or a normal person) actually types after a name. Ordered by how
# reliably they surface the load-bearing facts. Kept short and keyword-register on purpose.
PERSON_ANGLES = [
    "cause of death",          # the single highest-yield probe for a deceased/missing person
    "missing",
    "obituary",
    "news",
    "updates",
    "investigation police",
    "family statement",
    "conspiracy",              # surfaces the CLAIM so the Pattern-Claim organ can adjudicate it
    "interview",
    "research work",
]

# Scaffolding we write for the LLM that must NEVER reach a search engine.
_INSTRUCTION_PATTERNS = [
    r"^verify (the )?identity[^:]*:\s*",
    r"^verify (this|the) claim[^:]*:\s*",
    r"^verify independently[^:]*:\s*",
    r"^investigate this anomaly/discrepancy in detail,? and whether it holds up:\s*",
    r"^what evidence supports and,? crucially,? what evidence disconfirms this explanation:\s*",
    r"^complete authoritative list of all named individuals in:\s*",
    r"\s*\((peer-reviewed study|original paper)[^)]*\)\s*$",
    r"\s*from primary/authoritative sources\s*:?\s*",
    r"\s*and trace it to its primary/original source\s*:?\s*",
]


def strip_instructions(lead: str) -> str:
    """Remove our internal investigator scaffolding, leaving the actual search payload.
    'Verify the identity, current status... sources: Monica Reza' -> 'Monica Reza'."""
    s = " ".join((lead or "").split())
    for pat in _INSTRUCTION_PATTERNS:
        s = re.sub(pat, "", s, flags=re.I)
    return s.strip(" :;-—")


def person_queries(name: str, *, context: str = "", angles: list | None = None,
                   max_q: int = 8) -> list:
    """NAME + ANGLE fan-out — how an investigator actually searches (Gambit's design).
    `context` adds a disambiguating qualifier (employer/place) when the name is common.
    Returns short, keyword-register query strings."""
    name = " ".join((name or "").split())
    if not name:
        return []
    ctx = " ".join((context or "").split())[:40]
    # context (employer/role/case terms) disambiguates a COMMON name from a namesake. Apply it to
    # EVERY angle query, not just the bare-name one — 'Joshua LeBlanc cause of death' alone hooked a
    # prolific academic namesake (v11); 'Joshua LeBlanc missing scientist cause of death' does not.
    out = [f"{name} {ctx} {a}".replace("  ", " ").strip() if ctx else f"{name} {a}"
           for a in (angles or PERSON_ANGLES)]
    out.insert(0, name if not ctx else f"{name} {ctx}")
    seen, uniq = set(), []
    for q in out:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(q)
    return uniq[:max_q]


def qualify(query: str, *, place: str = "", when: str = "") -> str:
    """Add the place/date tokens that separate the right article from a name collision. The audit
    found NOT ONE query carried 'Huntsville' or '2022' — even though our own findings had them."""
    bits = [query]
    if place:
        bits.append(place)
    if when:
        bits.append(str(when))
    return " ".join(b for b in bits if b).strip()


def for_engine(queries: list, engine: str = "web", max_words: int = 12) -> list:
    """Format per engine. YouTube/podcast are LEXICAL over short human-written titles — long analyst
    prose matches nothing there, so hard-trim. Web/Exa is neural and tolerates more."""
    out = []
    for q in queries:
        # ALWAYS strip scaffolding BEFORE trimming — trimming first keeps the boilerplate and throws
        # away the payload ('Verify the identity, current status, and documented cause or outcome for
        # this' — name gone). Caught in verification 2026-07-21.
        q = strip_instructions(q)
        if not q:
            continue
        if engine in ("youtube", "podcast"):
            q = " ".join(q.split()[:max_words])
        out.append(q)
    return out


# Deterministic marks of a FOIA request rather than an investigator's question. Measured on v14:
# 75% of generated questions asked whether a document EXISTS, avg 35 words, 67% compound. The old
# gate graded with an LLM only, and the LLM happily passed them — so these patterns are now checked
# in plain Python first, where nothing can argue with them.
_DOC_EXISTENCE_RE = re.compile(
    r"^\s*(is|are|has|have|does|do)\s+(there\s+)?(any|there)?\b"
    r"|primary[- ]source\s+document|what\s+documentation|documentation\s+(exist|establish)"
    r"|what\s+primary[- ]source|official(ly)?\s+released\s+documents", re.I)
_MAX_Q_WORDS = 15


def bad_question(q: str) -> str:
    """Why this question is unusable, or '' if it's fine. Pure string checks — no LLM, no cost.
    An investigator asks 'Who found the body?'; these catch the 35-word paperwork interrogatories."""
    s = " ".join((q or "").split())
    if not s:
        return "empty"
    n = len(s.split())
    if n > _MAX_Q_WORDS:
        return f"too long ({n} words)"
    if _DOC_EXISTENCE_RE.search(s):
        return "asks whether a document exists instead of what happened"
    if s.count("?") > 1 or " and what " in s.lower() or "—" in s:
        return "compound (more than one question)"
    return ""


def preflight_gate(leads: list, *, context: str = "") -> list:
    """Question quality gate (Gambit: 'a smart question needs to be developed — the fetcher depends on
    every question asked'). Grade each lead A/B/C/F BEFORE any money is spent fetching for it; C/F
    leads get REWRITTEN into a sharp, retrievable question (proper nouns, concrete outcome, right
    register). One cheap LLM call for the whole list; fail-open returns the leads unchanged. Entity-
    verification template leads pass through untouched (they are already A-grade by construction)."""
    if not leads:
        return []
    # NO BLANKET EXEMPTION (2026-07-27). This used to skip every "Verify the identity..." lead as
    # "A-grade by construction" — but that template IS the boilerplate problem: 17 words of scaffolding
    # wrapped around a name, which the engines then had to have stripped back off. Anything the
    # deterministic checker rejects now gets sent for rewrite regardless of its shape.
    todo = [(i, l) for i, l in enumerate(leads)
            if bad_question(l) or not l.lower().startswith("verify the identity")]
    if not todo:
        return list(leads)
    try:
        from .memory.gap_detector import _reason_json
        # number by POSITION in the filtered list (0..n-1), not original index — models renumber from
        # 0 regardless of the labels shown, so original-index keys silently drop every rewrite
        # (caught in verification 2026-07-21: a C-graded lead with a good rewrite came back unchanged).
        blob = "\n".join(f'{j}. "{l[:200]}"' for j, (_, l) in enumerate(todo))
        # tell the model exactly which leads Python already rejected, and why — it cannot pass them
        flagged = {j: bad_question(l) for j, (_, l) in enumerate(todo) if bad_question(l)}
        flag_txt = ("\nALREADY REJECTED by automatic check — you MUST rewrite these:\n"
                    + "\n".join(f"  {j}: {why}" for j, why in flagged.items()) if flagged else "")
        prompt = (
            "You are a question-quality gate for an investigation engine. Each INVESTIGATIVE LEAD "
            "below will drive real web/video searches, so a vague or badly-phrased lead wastes money "
            "and retrieves junk. Grade each A/B/C/F and rewrite every C or F.\n"
            "WHAT AN 'A' LEAD LOOKS LIKE — a question a detective would type into a search box:\n"
            "- UNDER 12 WORDS. ONE question. Names something specific (person, place, date, document).\n"
            "- Asks WHAT HAPPENED, never whether a record exists. Automatic F: anything opening 'Is "
            "there any...', 'Are there any...', 'Has any...', 'Have any...', 'What primary source "
            "documents...'. Primary sourcing is the standard the ANSWER must meet — never the "
            "subject of the question.\n"
            "- Automatic F: instruction-shaped scaffolding ('Verify the identity, current status and "
            "documented cause or outcome for this individual from primary/authoritative sources: X') "
            "-> rewrite as 'What happened to X?' or 'How did X die?'\n"
            "GOOD: 'Who found Carl Grillmair's body?' · 'What did Reza's last text say?' · "
            "'Which AFRL program employed McCasland?'\n"
            "BAD: 'What primary-source documents explicitly confirm the verified status and "
            "documented circumstances for Monica Jacinto Reza?'\n"
            + flag_txt + "\n"
            + (f"CASE CONTEXT: {context[:200]}\n" if context else "") +
            f"\nLEADS:\n{blob}\n\n"
            'Return STRICT JSON: {"gates": [{"i": 0, "grade": "A", "rewrite": null}]}')
        data = _reason_json(prompt)
        gm = {g.get("i"): g for g in (data.get("gates") or []) if isinstance(g, dict)} \
            if isinstance(data, dict) else {}
        out = list(leads)
        for j, (i, _) in enumerate(todo):    # j = position shown to the model; i = original index
            g = gm.get(j, {})
            rw = g.get("rewrite")
            if g.get("grade") in ("C", "F") and rw and str(rw).strip():
                out[i] = str(rw).strip()
        return out
    except Exception:
        return list(leads)


def plan_queries(question: str, *, entities: list | None = None, engine: str = "web",
                 n: int = 6) -> list:
    """Ask the model what an expert would actually TYPE into this engine (Gambit: 'ask claude/grok/
    google what we should be searching'). Used for topical/non-person leads and novel cases where the
    fixed angle list doesn't apply. Returns SHORT keyword queries. Fail-open to a stripped fallback."""
    q = strip_instructions(question)
    if not q:
        return []
    ents = ", ".join(str(e) for e in (entities or [])[:8])
    try:
        from .memory.gap_detector import _cheap_json
        prompt = (
            "You are an expert investigative researcher. Given the CASE below, write the exact search "
            f"queries you would TYPE INTO {engine.upper()} to find the load-bearing facts.\n"
            "RULES: short KEYWORD queries (3-8 words), the way a person actually searches — NOT "
            "questions, NOT instructions, NOT full sentences. Use proper nouns (names, places, "
            "organizations) and add year/place qualifiers where they disambiguate. Vary the ANGLE "
            "across queries (what happened, cause, official response, the person's work, claims made "
            "about it, criticism/dispute). No boilerplate.\n\n"
            f"CASE: {q}\n" + (f"KEY ENTITIES: {ents}\n" if ents else "") +
            f'\nReturn STRICT JSON: {{"queries": ["...", "..."]}} with {n} queries.')
        data = _cheap_json(prompt)
        out = []
        for x in (data.get("queries") or []) if isinstance(data, dict) else []:
            s = " ".join(str(x).strip().strip('"').split())
            if s and s.lower() not in {o.lower() for o in out}:
                out.append(s)
        if out:
            return for_engine(out[:n], engine)
    except Exception:
        pass
    return for_engine([q], engine)
