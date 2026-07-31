"""Quill — the Correspondent (Seeker's reporting/editorial organ).

Gambit's call (2026-07-16): Seeker gathers superbly but REPORTS flatly. The doctor's-diagnosis
"deliver it straight" rule got over-read as "deliver it BORING" — the missing-scientists report
flattened genuinely striking, odd, unresolved facts into "nothing to see." That erases the very
texture that makes an investigation worth reading.

Quill fixes that. Two jobs:
  1. report()  — write the findings as long-form investigative journalism (Keefe / Grann / Wright
                 school): a human thread, the genuinely notable details drawn OUT not smoothed away,
                 the honest verdict landing HARDER because the tension was earned first.
  2. critique() — read any Seeker output and flag flatness, buried ledes, missing human thread.

Hard guardrail (Vera): engaging =/= sensational. Every striking detail must trace to a real finding;
Quill NEVER invents mystery, spins, or manufactures intrigue. Honest nuance, not skepticism-for-effect.
Grounded-only — same spine as synthesis. Names use the authoritative spelling (see name-fidelity, #23).
"""
from __future__ import annotations

import json
import os

import requests

from . import config
from . import synthesis as _synthesis

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# a capable WRITER model (prose quality matters); override via env. Default is a strong mid model,
# not the mini extractor (too flat) nor opus (too costly for a routine report).
# BIAS-ROUTED (2026-07-27, task #37): the writer is now chosen by the MEASURED lean card
# (runs/bias_lean_card.md) instead of a hardcoded guess — bias_probe.py measured which model softens
# and strips least, and for months nothing read that measurement. synthesis_model() closes the loop;
# an explicit QUILL_MODEL env or SEEKER_BIAS_ROUTING=0 still wins (human override beats the card).
def _writer_model() -> str:
    try:
        from .publisher_reviewer import synthesis_model
        return synthesis_model(default=os.environ.get("QUILL_MODEL", "openai/gpt-4.1"))
    except Exception:
        return os.environ.get("QUILL_MODEL", "openai/gpt-4.1")


_QUILL_MODEL = _writer_model()


def _llm(prompt: str, *, as_json: bool, model: str = _QUILL_MODEL) -> str | dict:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if as_json:
        body["response_format"] = {"type": "json_object"}
    r = requests.post(_OPENROUTER_URL,
                      headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                               "Content-Type": "application/json"},
                      json=body, timeout=max(120, config.REQUEST_TIMEOUT))
    r.raise_for_status()
    out = r.json()["choices"][0]["message"]["content"]
    return json.loads(out) if as_json else out


def _rows(bucket, limit=18):
    return "\n".join(f"- {r['claim']}" for r in bucket[:limit]) or "(none)"


def _name_roster(buckets: dict) -> tuple:
    """Canonical entity roster + flagged garbles across the findings, via the entity resolver — the
    ground truth Quill must spell names by. Returns (canonical_names, suspect_names). Fail-open."""
    try:
        from .entity_resolution import resolve_entities
        findings = []
        for label in ("well-supported", "contested", "unverified", "disproven"):
            findings += buckets.get(label, [])
        res = resolve_entities(findings)
        roster = [c["canonical"] for c in res.get("entities", []) if not c.get("suspect")]
        return roster, list(res.get("suspect_names", []))
    except Exception:
        return [], []


def notable_threads(question: str, *, branch_id: str = "main", mm=None,
                    top_k: int | None = None) -> list:
    """Extract the GENUINELY notable, odd, or unresolved-but-interesting facts on the map — the
    details that would make a smart reader lean in. Grounded ONLY in findings; no invented mystery
    (Vera). Returns [{"thread","why"}]. Fail-open to []."""
    try:
        buckets = _synthesis.gather_findings(question, branch_id=branch_id, top_k=top_k, mm=mm)
        blob = ""
        for label in ("well-supported", "contested", "unverified"):
            blob += f"\n[{label}]\n{_rows(buckets.get(label, []))}\n"
        prompt = (
            "You are an investigative reporter reviewing verified case findings. List the GENUINELY "
            "notable facts — the striking, odd, surprising, or unresolved-but-interesting details a "
            "sharp reader would lean in on. HARD RULES: every item must be a REAL fact from the "
            "findings below (quote/paraphrase it) — invent NOTHING, manufacture NO mystery, spin "
            "NOTHING. 'Notable' means genuinely interesting-and-true, not sensational. If a fact is "
            "striking precisely because it's mundane-yet-unresolved, that counts. Skip the boring.\n\n"
            f"CASE: {question}\n\nFINDINGS:\n{blob}\n\n"
            'Return STRICT JSON: {"threads": [{"thread": "the notable fact", "why": "why it lands, '
            'one line"}]} — up to 8, best first.')
        data = _llm(prompt, as_json=True)
        out = []
        for t in (data.get("threads", []) if isinstance(data, dict) else []):
            if isinstance(t, dict) and str(t.get("thread", "")).strip():
                out.append({"thread": str(t["thread"]).strip(), "why": str(t.get("why", "")).strip()})
        return out[:8]
    except Exception:
        return []


def report(question: str, *, branch_id: str = "main", mm=None, top_k: int | None = None,
           profiles: list | None = None) -> dict:
    """Write the case as long-form investigative journalism. Returns {"report","notable_threads"}.

    top_k=500, NOT 50 (fix 2026-07-28). FOURTH occurrence of the fixed-window class, and the worst:
    Quill wrote v18's report from ~7% of a 700-finding corpus and duly announced "for most of these
    named individuals there is no publicly available, independently verified status or cause" — while
    the SAME run's entity profiles held 9 DECEASED and 4 MISSING with causes. The reporting layer was
    telling the reader the investigation failed, because it could not see the investigation. I fixed
    synthesis (40->500) and never checked next door.
    Grounded in the map; engaging but never sensational; the honest verdict is kept, not softened."""
    try:
        buckets = _synthesis.gather_findings(question, branch_id=branch_id, top_k=top_k, mm=mm)
        threads = notable_threads(question, branch_id=branch_id, mm=mm, top_k=top_k)
        tblob = "\n".join(f"- {t['thread']} ({t['why']})" for t in threads) or "(none surfaced)"
        # NAME FIDELITY (task #26): the entity resolver merges token-matching variants, but a PHONETIC
        # garble ("Casias" -> "Cascio") doesn't token-match, so it survives as a suspect name and leaks
        # into prose. Give Quill the canonical roster + the flagged garbles so it uses the right spelling
        # and never prints a garble — the fact-check step enforces it. Fail-open (empty roster = no-op).
        roster, suspects = _name_roster(buckets)
        roster_txt = ", ".join(roster[:30]) or "(none resolved)"
        susp_txt = ", ".join(suspects[:20]) or "(none)"
        # ESTABLISHED FACTS SPINE (2026-07-28) — the fix for a subtle, real retrieval defect.
        # Retrieval is semantic, so a claim that ECHOES the question outranks one that ANSWERS it:
        # asked about "verified status and documented cause", the top-ranked finding was "there is no
        # publicly available independently verified status or cause for [ten names]" — a near-perfect
        # vocabulary match, and sweeping. Quill opened its evidence, saw several blanket no-status
        # claims above the individual facts, and wrote that the record was silent — while the SAME
        # run's per-person profiles held 9 DECEASED with causes and 4 MISSING. The profiles are
        # computed per entity, so they cannot be crowded out by an echo. They are the factual spine;
        # the findings supply texture. Fail-open: no profiles = previous behaviour.
        prof_txt = "(not supplied)"
        if profiles:
            prof_txt = "\n".join(
                f"- {p.get('name','')}: {str(p.get('status','unknown')).upper()}"
                + (f" — {p['cause']}" if p.get("cause") else "")
                + (f" | {str(p.get('detail',''))[:150]}" if p.get("detail") else "")
                for p in profiles[:30])
        prompt = (
            "You are Quill, a long-form investigative journalist in the school of Patrick Radden "
            "Keefe, David Grann, and Lawrence Wright. Write a tight, gripping report of THIS case "
            "from the verified findings — the kind a smart reader can't stop reading.\n\n"
            f"ESTABLISHED STATUS OF EACH PERSON (authoritative — this is what the investigation "
            f"actually determined, resolved per-person):\n{prof_txt}\n\n"
            "PRECEDENCE: the per-person statuses above OVERRIDE any sweeping finding that claims no "
            "status is known. A blanket 'no verified status exists for these people' outranks nothing "
            "— if the list above gives a person a status and cause, that person HAS one and you must "
            "report it. Never tell the reader the record is silent about someone the investigation "
            "resolved. You may still report, accurately, where PRIMARY-SOURCE documentation is "
            "missing — but say that precisely ('no coroner report has been released') rather than as "
            "a blanket absence of knowledge.\n\n"
            # VOICE, resolved 2026-07-28 (Gambit's call: "write plainly, neutrality wins"). Quill was
            # told to be gripping — "Keefe/Grann, let tension build" — while the Publisher-Reviewer was
            # told to flag any language presuming more than the evidence carries. Two organs with
            # OPPOSING objectives: Quill wrote "a dissonant symphony of unanswered questions" and "the
            # shroud of secrecy is chilling", each doing exactly as instructed, and the report failed
            # the gate three rewrites running. Neutrality wins. But "plain" is NOT the flatness Quill
            # was built to fix: the striking facts still lead and still land — the PROSE just stops
            # adding atmosphere on top of them. That is the actual Keefe discipline anyway; he does not
            # write "chilling", he reports the detail that IS chilling and gets out of the way.
            "VOICE: plain, precise, human. State what happened in clean declarative sentences and let "
            "the facts carry their own weight. Open on the most concrete specific fact — a person, a "
            "date, a place, an object — never a mood or a rhetorical question. Draw the genuinely "
            "NOTABLE details OUT (do not smooth them into 'nothing to see'), but present them "
            "STRAIGHT: the reader supplies the reaction, you supply the fact.\n"
            "BANNED, without exception: atmospheric or editorialising language — 'chilling', 'grim', "
            "'haunting', 'shroud of secrecy', 'unnerving', 'stark', 'a dissonant symphony', 'casts a "
            "light', 'sends a shiver', or any metaphor that implies menace the evidence does not "
            "establish. No rhetorical questions. No scene-setting you did not find in a source. If a "
            "sentence would survive unchanged in a police report or a wire story, it is right; if it "
            "reads like a documentary voice-over, delete it.\n"
            "HARD RULES (non-negotiable): use ONLY the findings — invent NOTHING, manufacture NO "
            "mystery, no sensationalism, no spin. Every striking detail must be a real finding. Keep "
            "the honest verdict and tier labels (well-supported / contested / unverified / disproven) "
            "TRUE — engaging must never cost accuracy. Deliver figures with their basis. Name people "
            "with the spelling from the most authoritative finding. Do not accuse anyone. ~300-500 "
            "words, a real ending (not 'further research needed'). The ending states what is "
            "established and what remains open — it does not gesture at significance.\n"
            "NAME FIDELITY: the CANONICAL NAMES below are the correct spellings — use them EXACTLY. The "
            "SUSPECT NAMES are known transcription garbles; if the findings mention one, use the matching "
            "canonical name instead, never the garble. Do NOT merge two genuinely different people who "
            "merely have similar names — only fix an obvious misspelling of a canonical name.\n"
            f"CANONICAL NAMES: {roster_txt}\nSUSPECT NAMES (garbles — do not print): {susp_txt}\n\n"
            f"CASE: {question}\n\n"
            f"NOTABLE THREADS (surfaced):\n{tblob}\n\n"
            f"WELL-SUPPORTED:\n{_rows(buckets.get('well-supported', []))}\n\n"
            f"CONTESTED:\n{_rows(buckets.get('contested', []))}\n\n"
            f"UNVERIFIED:\n{_rows(buckets.get('unverified', []))}\n\n"
            f"DISPROVEN:\n{_rows(buckets.get('disproven', []))}\n\n"
            "Return the report as PLAIN PROSE (no JSON, no headers unless they serve the story).")
        draft = (_llm(prompt, as_json=False) or "").strip()
        # ACCURACY FLOOR (#24): fact-check the draft against the findings before returning — the
        # doctrine's non-negotiable. Fixes confabulation (v1 mislocated Reza to make prose flow).
        checked = _fact_check(draft, buckets, roster=roster, suspects=suspects)
        prose, corrections = checked["report"], checked["corrections"]
        # SELF-REVISION (Gambit): the editor kept flagging the report as flat (buried lede, human
        # thread dropped) and NOTHING acted on it. Close the loop: critique our own draft, and if it's
        # flat, revise against that critique — THEN re-fact-check so livelier prose never buys
        # confabulation. One pass (cost control); the director still critiques the final for the ledger.
        self_revised = False
        crit = critique(prose)
        if crit.get("flat"):
            revised = _revise(prose, crit, buckets)
            if revised and revised.strip() and revised.strip() != prose.strip():
                regrounded = _fact_check(revised.strip(), buckets, roster=roster, suspects=suspects)
                prose = regrounded["report"]
                corrections += [f"(self-revised for engagement) {c}" for c in regrounded["corrections"]]
                self_revised = True
        # VOICE GATE — the LAST stage, mechanically enforced, so nothing downstream re-adds
        # atmosphere. Up to two strip passes; the fact-check re-runs after each because a rewrite
        # that loses a fact is worse than one that keeps an adjective. If violations survive both
        # passes they are RETURNED, not swallowed — the caller (and the log) see exactly what still
        # breaks the rule instead of a report that quietly failed its own standard.
        voice_left = []
        for _pass in range(2):
            voice_left = voice_violations(prose)
            if not voice_left:
                break
            stripped = _strip_voice(prose, voice_left)
            if stripped and stripped.strip():
                rechecked = _fact_check(stripped.strip(), buckets, roster=roster, suspects=suspects)
                prose = rechecked["report"]
                corrections += [f"(voice gate) removed: {v}" for v in voice_left[:8]]
        voice_left = voice_violations(prose)
        return {"report": prose, "corrections": corrections,
                "notable_threads": threads, "self_revised": self_revised,
                "voice_violations_left": voice_left,
                "pre_revision_critique": crit}
    except Exception as e:
        return {"report": "", "notable_threads": [], "corrections": [], "error": repr(e)[:120]}


def _revise(prose: str, crit: dict, buckets: dict) -> str:
    """Quill rewrites its OWN draft to fix what its editor flagged — lead with the human thread, surface
    the notable facts, un-bury the lede, kill bureaucratic voice — using ONLY the findings and keeping
    the honest verdict. Returns revised prose ('' on failure, caller keeps the original)."""
    issues = "; ".join(crit.get("issues", []))
    fixes = "; ".join(crit.get("fixes", []))
    if not (issues or fixes):
        return ""
    try:
        facts = ""
        for label in ("well-supported", "contested", "unverified", "disproven"):
            facts += f"\n[{label}]\n{_rows(buckets.get(label, []), 20)}\n"
        prompt = (
            "You are Quill. Your editor read your draft and flagged it as FLAT. Rewrite it to fix "
            "EXACTLY these problems — open on a concrete human thread or scene, un-bury the lede, draw "
            "the genuinely notable details OUT instead of smoothing them, and kill any bureaucratic "
            "voice. Let honest tension build before the verdict lands.\n"
            f"EDITOR ISSUES: {issues}\nEDITOR FIXES: {fixes}\n\n"
            "HARD RULES: use ONLY the findings below — invent NOTHING, manufacture no mystery, no "
            "sensationalism. Keep the honest verdict and tier labels TRUE. Do not accuse anyone. Keep "
            "roughly the same length and a real ending.\n\n"
            f"FINDINGS:\n{facts}\n\nDRAFT TO REVISE:\n{prose}\n\n"
            "Return the revised report as PLAIN PROSE (no JSON).")
        return (_llm(prompt, as_json=False) or "").strip()
    except Exception:
        return ""


def _fact_check(prose: str, buckets: dict, *, roster: list | None = None,
                suspects: list | None = None) -> dict:
    """Fact-fidelity guard (#24) — the accuracy floor. Check every SPECIFIC in the draft (name, place,
    date, role, number) against the findings; correct or CUT anything not supported. This fixes the
    confabulation class (v1 put Reza at Los Alamos to make prose flow). With `roster`/`suspects` it also
    fixes PHONETIC name garbles (#26) the token-based resolver can't merge ("Cascio" -> "Casias"): the
    canonical roster is the ground truth, the suspect list is known garbles to replace. Returns
    {report, corrections}."""
    try:
        facts = ""
        for label in ("well-supported", "contested", "unverified", "disproven"):
            facts += f"\n[{label}]\n{_rows(buckets.get(label, []), 24)}\n"
        name_rule = ""
        if roster:
            name_rule = (
                "\nNAME FIDELITY: CANONICAL NAMES are the correct spellings — every person name in the "
                "report must match one EXACTLY. SUSPECT NAMES are known transcription garbles; if the "
                "draft prints one (or any near-misspelling of a canonical name), replace it with the "
                "matching canonical name. Do NOT merge two genuinely different people with similar names "
                "— only fix an obvious garble of a canonical name.\n"
                f"CANONICAL NAMES: {', '.join(roster[:30])}\n"
                f"SUSPECT NAMES (garbles): {', '.join((suspects or [])[:20]) or '(none)'}\n")
        prompt = (
            "You are a scrupulous fact-checker for an investigative report. Below is a DRAFT and the "
            "verified FINDINGS it must rest on. Rewrite the draft so that EVERY specific detail — "
            "person, place, employer, role, date, number — is SUPPORTED by the findings. Correct any "
            "detail that contradicts the findings; CUT any specific the findings do not support (keep "
            "the sentence, drop the unsupported specifics). When a person's name appears several ways "
            "across findings, use the spelling from the most authoritative/primary finding. Preserve "
            "the voice, structure, and length. Add NO new claims. Do not soften the verdict.\n"
            f"{name_rule}\n"
            f"FINDINGS:\n{facts}\n\nDRAFT:\n{prose}\n\n"
            'Return STRICT JSON: {"report": "the corrected report", "corrections": ["what you fixed '
            'or cut, one line each"]}')
        data = _llm(prompt, as_json=True)
        if isinstance(data, dict) and str(data.get("report", "")).strip():
            return {"report": str(data["report"]).strip(),
                    "corrections": [str(c) for c in (data.get("corrections") or [])][:12]}
    except Exception:
        pass
    return {"report": prose, "corrections": []}


# ---------------------------------------------------------------------------------------------
# VOICE GATE (2026-07-29) — the banned-phrase list, enforced as CODE.
#
# The list already existed, spelled out in Quill's prompt: no atmospheric language, no rhetorical
# questions, open on a concrete fact and never on a mood. v19 opened with "The hum that usually
# precedes the morning's frantic pace", called the case "something far more sinister", and closed on
# "a reckoning with forces yet unknown" — every clause the prompt forbids, in one draft, hours after
# the prompt was written. The writer is a cheap model being handed a long list of prohibitions; that
# is the weakest possible way to enforce anything.
#
# This is the same move that beat the namesake problem today: three prose guards failed, one
# deterministic year check worked. A rule a model is ASKED to follow is a suggestion. A rule that is
# CHECKED is a rule. Violations here are found by regex, and the draft does not leave this function
# while any remain and rewrites are left.
_BANNED = [
    "chilling", "grim", "haunting", "shroud of secrecy", "unnerving", "sinister", "eerie",
    "sends a shiver", "casts a light", "dissonant symphony", "forces yet unknown", "unseen threat",
    "palpable", "etched in", "cut through the din", "scrambling to understand", "dark truth",
    "growing list of concern", "something far more", "hangs over", "shadow", "ominous", "chilling",
    "disturbing pattern", "deeply unsettling", "reckoning with", "the stakes are immense",
]


def voice_violations(text: str) -> list:
    """Every place the draft breaks the voice rule. Deterministic — no model judgment involved.

    Three classes, each one an actual v19 failure:
      BANNED PHRASE  — atmosphere asserting menace the evidence does not carry.
      RHETORICAL Q   — v19 ended by asking whether the nation faced "forces yet unknown". A report
                       states what is known; a question invites the reader to supply a conspiracy.
      MOOD OPENER    — the first sentence must carry a concrete anchor (a capitalised name, a date,
                       a number). "The hum that usually precedes the morning's frantic pace" carries
                       none, which is exactly how a report starts sounding like a trailer."""
    import re as _r
    out = []
    low = (text or "").lower()
    for b in sorted(set(_BANNED)):
        if b in low:
            out.append(f"banned phrase: '{b}'")
    for s in _r.findall(r"[^.!?]*\?", text or ""):
        if len(s.strip()) > 12:
            out.append(f"rhetorical question: '{s.strip()[:70]}'")
    first = ((text or "").strip().split(".") or [""])[0]
    # A concrete anchor is a name, a date, a figure — OR a spelled-out count. The first cut looked
    # only for a capital or a digit after the opening three characters, so "Thirteen individuals
    # with scientific or defense affiliations..." was flagged as atmosphere. That sentence opens on
    # the single most concrete fact in the dossier. A gate that objects to correct writing gets
    # switched off, and then it is not there for the sentence that actually needed it.
    _NUMWORD = (r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
                r"fourteen|fifteen|twenty|thirty|forty|fifty|hundred)\b")
    if first and not (_r.search(r"\b[A-Z][a-z]{2,}|\b\d+\b", first[3:])
                      or _r.search(_NUMWORD, first, _r.I)):
        out.append(f"mood opener (no concrete anchor): '{first[:70]}'")
    return out


def _strip_voice(prose: str, violations: list) -> str:
    """Targeted rewrite: delete the offending language, keep every fact. Deliberately NOT a general
    'improve this' pass — those drift and re-add atmosphere elsewhere."""
    listed = "\n".join(f"- {v}" for v in violations[:20])
    return (_llm(
        "Rewrite the REPORT below to remove these specific voice violations, and nothing else.\n"
        + listed +
        "\n\nRULES: keep EVERY fact, name, date and figure exactly as written — this is a deletion "
        "and rephrasing pass, not a rewrite. Remove atmospheric wording rather than replacing it with "
        "different atmospheric wording. Turn any rhetorical question into a plain statement of what "
        "is and is not established, or delete it. The opening sentence must begin with a concrete "
        "fact: a named person, a date, or a figure. If a sentence would survive unchanged in a wire "
        "story, leave it alone.\n\nREPORT:\n" + (prose or ""), as_json=False) or "").strip()


def critique(text: str) -> dict:
    """Quill as EDITOR: read a piece of Seeker output and flag flatness / buried lede / missing human
    thread — 'is this a good way to display our research?' Returns {"flat","issues","fixes"}."""
    try:
        prompt = (
            "You are Quill, a demanding investigative editor. Critique the report below on ONE axis: "
            "is it a compelling way to display complex research, or is it flat? Flag specifically: a "
            "buried lede, a missing human thread, genuinely interesting facts smoothed into 'nothing "
            "to see,' bureaucratic voice. Be blunt. Do NOT ask for more skepticism or invented "
            "mystery — only for HONEST engagement with what's already there.\n\n"
            f"REPORT:\n{text[:6000]}\n\n"
            'Return STRICT JSON: {"flat": true/false, "issues": ["..."], "fixes": ["concrete fix"]}')
        data = _llm(prompt, as_json=True)
        if not isinstance(data, dict):
            return {"flat": False, "issues": [], "fixes": []}
        return {"flat": bool(data.get("flat")),
                "issues": [str(x) for x in (data.get("issues") or [])][:6],
                "fixes": [str(x) for x in (data.get("fixes") or [])][:6]}
    except Exception:
        return {"flat": False, "issues": [], "fixes": []}
