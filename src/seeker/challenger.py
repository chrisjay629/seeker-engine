"""The Challenger gate — a MECHANISM for the checks that never stuck as prose (task #39).

WHY THIS EXISTS. Gambit, 2026-07-28: "a lot of the stuff we suggest as a prompt and not necessarily
coding doesn't apply well or initiate correctly." He is right, and this session is the proof. Three
separate times this session I looked at generated questions and called them "investigator-grade"
while they were 35-word paperwork interrogatories. There were memory notes telling me to be skeptical
about exactly this. They did not fire. Meanwhile:

  * `bad_question()` — a plain Python function — caught 40/40 of the same questions instantly
  * `test_wiring.py` went red when I aliased a function to hide it
  * my own gate rejected my own template, in the same hour I wrote the rule

The lesson is not "be more careful". It is:

    PROSE IS ADVISORY. CODE IS BINDING.

A note competes with my judgment and loses. A gate overrides it. So every check we want to actually
hold has to stop being a note and become a mechanism. This module is where those live.

TWO FAILURE MODES IT IS BUILT AGAINST (both mine, both observed this session):
  1. SCORING SURFACE MARKERS INSTEAD OF FUNCTION. Long, hedged, methodological-sounding text reads as
     rigorous. "cited by name, date, and recording" hits every marker of care and retrieves essays
     about e-mail etiquette. Gambit's test was functional — "would a real investigator SEARCH this?"
     — and it took him seconds. So every criterion here asks DOES IT WORK, never DOES IT LOOK GOOD.
  2. SELF-REVIEW. I generated those questions and then judged them with the same system that produced
     them. The judgment layer therefore runs on a DIFFERENT model (same principle as
     publisher_reviewer), and must QUOTE the offending sample — a flag with no quote is an opinion.

THREE LAYERS, because "what about a failure it has never seen?" is the right question:
  * DETERMINISTIC — known classes, exactly, forever, free, unarguable. Blind to anything new.
  * JUDGMENT      — a different model with functional criteria; generalises to novel failures.
  * ESCALATION    — the actual answer. The danger is not hitting an unknown wall, it is hitting one
                    and SILENTLY SAYING OK. So: uncertainty escalates, it never passes.

AND IT GROWS. Every miss Gambit catches becomes a new deterministic check in _DETERMINISTIC below.
The wall becomes a rule, so the same wall is never hit twice — which is precisely what failed to
happen with question quality across fourteen runs.
"""
from __future__ import annotations

import os
import re

_MAX_SAMPLES = 12

# sentence-initial / generic capitalised words that are not entity claims
_STOP_CAPS = {"who", "what", "when", "where", "which", "why", "how", "was", "were", "did", "does",
              "the", "and", "for", "his", "her", "their", "any", "are", "can", "has", "have"}

# CALIBRATION ANCHORS (2026-07-28). First live test flagged "Who filed the missing person report for
# Melissa Casias?" as "overly-generic" — one of the questions Gambit CONFIRMED as the target. A gate
# that cries wolf gets ignored, and an ignored gate is worse than none: it launders bad output with a
# verdict nobody reads (Noor). So the reviewer is shown what CONFIRMED-GOOD looks like and told that
# flagging it is itself a failure. Source: project-seeker-question-standard (v15, Gambit's own words).
_GOOD_EXEMPLARS = {
    "questions": [
        "Who filed the missing person report for Melissa Casias?",
        "Who discovered Nuno Loureiro's body in Brookline, Massachusetts?",
        "What firearms were found in the Salem storage unit?",
        "How did Joshua LeBlanc die?",
    ],
}


# ---------------------------------------------------------------------------------------------
# LAYER 1 — DETERMINISTIC. Known failure classes, as plain code. Add one every time Gambit catches
# something this missed; that is the growth path, and it is the whole point.
# ---------------------------------------------------------------------------------------------

def _dc_questions(samples: list, ctx: dict) -> list:
    """Question-shaped output. The class that survived 14 runs because nothing mechanical checked it."""
    from .search_queries import bad_question
    flags = []
    for s in samples:
        why = bad_question(s)
        if why:
            flags.append({"kind": "unusable-question", "why": why, "sample": s[:200]})
    # ALL-SAME-SHAPE: a generator emitting one template with the nouns swapped is not asking
    # questions, it is filling in a form. Caught by looking at openings, not at any single sample.
    heads = [" ".join(s.split()[:3]).lower() for s in samples if s.split()]
    if len(heads) >= 4 and len(set(heads)) <= max(1, len(heads) // 4):
        flags.append({"kind": "template-monoculture",
                      "why": f"{len(set(heads))} distinct openings across {len(heads)} questions — "
                             "this is a form being filled in, not questions being asked",
                      "sample": samples[0][:200] if samples else ""})
    return flags


def _dc_findings(samples: list, ctx: dict) -> list:
    """Retrieved evidence. Built for the namesake/off-case contamination class: v14 spent ~200
    findings on a tourism professor named Joshua LeBlanc; v15's follow-up hop chased Kilmar Abrego
    Garcia (a different man entirely) off the back of 'Steven Garcia'."""
    flags = []
    subject_terms = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", ctx.get("case", ""))}
    if subject_terms:
        for s in samples:
            words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", s)}
            if words and not (words & subject_terms):
                flags.append({"kind": "possibly-off-case",
                              "why": "shares no substantive term with the case — check it is the "
                                     "right person/subject and not a namesake",
                              "sample": s[:200]})
    return flags


def _dc_generic(samples: list, ctx: dict) -> list:
    flags = []
    for s in samples:
        if len(s.split()) < 3:
            flags.append({"kind": "empty-or-stub", "why": "too short to be real output",
                          "sample": s[:200]})
    return flags


_DETERMINISTIC = {
    "questions": _dc_questions,
    "findings": _dc_findings,
}

# Functional criteria per artifact kind — DOES IT WORK, never DOES IT LOOK GOOD. Gambit's test.
_CRITERIA = {
    "questions": (
        "Would a real investigator TYPE this into a search box and get the answer? Simulate it. "
        "A question that merely SOUNDS rigorous ('primary-source documentation', 'cited by name, "
        "date and recording') but retrieves nothing is a FAILURE, not a strength — verbose "
        "methodological wording is the specific trap here. Also: does each question chase a "
        "SPECIFIC detail (a name, time, place, object), or would it fit any case at all?"),
    "findings": (
        "Does this evidence actually ANSWER what was asked, or does it merely share vocabulary with "
        "the question? Is every item about the RIGHT subject — not a namesake or an unrelated case "
        "that happens to use similar words?"),
    "report": (
        "Is every claim traceable to the evidence? Does it state anything more strongly than its "
        "source does — especially about a named real person? Does it OMIT people or findings that "
        "exist in the evidence?"),
}


def _samples_of(samples) -> list:
    return [" ".join(str(s).split()) for s in (samples or []) if str(s).strip()][:_MAX_SAMPLES]


def challenge(kind: str, samples: list, *, case: str = "", claim: str = "",
              expected: str = "") -> dict:
    """Challenge generated output BEFORE anyone characterises it as good.

    kind     — "questions" | "findings" | "report" | anything (falls back to generic checks)
    samples  — the RAW artifacts. Not a summary. The display IS the check: Gambit caught the
               question defect the instant the raw questions were printed, after they had sat
               unexamined for a whole session.
    case     — case/subject context, used for the off-case (namesake) check
    claim    — what is ABOUT to be asserted about this output ("the questions are investigator-
               grade"). The gate tests the CLAIM against the SAMPLES. This targets the exact
               failure mode it was built for.
    expected — what SHOULD be present, if known. Enables the absence check ("is that it? no
               follow-ups?") — the question that found the missing loop.

    Returns {"verdict": "pass"|"fail"|"escalate", "flags":[{kind,why,sample}], "samples":[...],
             "reviewer_model": str, "n_checked": int}.

    NEVER returns "pass" on uncertainty. An unknown situation escalates to a human — because the
    danger was never hitting an unfamiliar wall, it was hitting one and silently approving.
    """
    out = {"verdict": "escalate", "flags": [], "questions": [], "samples": [],
           "reviewer_model": "", "n_checked": 0}
    if os.environ.get("SEEKER_CHALLENGER", "1") == "0":
        out["verdict"] = "pass"
        return out
    rows = _samples_of(samples)
    out["samples"] = rows
    out["n_checked"] = len(rows)
    if not rows:
        out["flags"].append({"kind": "no-output", "why": "nothing to check — absence is itself a "
                                                         "finding, not a pass", "sample": ""})
        return out                                   # escalate

    ctx = {"case": case}
    # ---- layer 1: deterministic ----
    out["flags"] += _DETERMINISTIC.get(kind, lambda s, c: [])(rows, ctx)
    out["flags"] += _dc_generic(rows, ctx)

    # ---- layer 2: judgment, on a DIFFERENT model, forced to quote ----
    try:
        from .publisher_reviewer import synthesis_model, reviewer_model
        from .memory.gap_detector import _cheap_json
        rmodel = reviewer_model(synthesis_model())
        out["reviewer_model"] = rmodel
        blob = "\n".join(f"{i + 1}. {s[:300]}" for i, s in enumerate(rows))
        data = _cheap_json(
            "You are the CHALLENGER — a red-team reviewer for an investigation engine. You did NOT "
            "produce this output. Your job is to find where it FAILS IN USE, not to appraise how it "
            "reads. Text that sounds careful and thorough while doing nothing is the single most "
            "common defect here; treat polish as a warning sign, not evidence of quality.\n\n"
            f"FUNCTIONAL TEST — {_CRITERIA.get(kind, 'Does this actually do its job when used?')}\n\n"
            + (("CALIBRATION — these are CONFIRMED-GOOD examples of this artifact, ratified by the "
                "project owner. Output of this quality MUST pass. Flagging work this good is itself "
                "a failure: a reviewer that cries wolf gets ignored, and then it protects nothing.\n"
                + "\n".join(f"  GOOD: {g}" for g in _GOOD_EXEMPLARS[kind]) + "\n\n")
               if kind in _GOOD_EXEMPLARS else "")
            + "Both errors cost the same. Missing a real defect is bad; flagging sound work is "
              "equally bad. Flag what genuinely FAILS IN USE — not what could theoretically be "
              "sharper. Do not invent hypothetical retrieval problems for a question that plainly "
              "names a person, a place, a date or an object.\n\n"
            "RULES: every flag MUST quote the specific sample it refers to — a flag without a quote "
            "is an opinion, not a finding. If you cannot tell whether it works, say so honestly via "
            "\"uncertain\": true; do NOT guess in either direction. Passing something you are unsure "
            "about is the worst outcome available to you.\n"
            + (f"\nSOMEONE IS ABOUT TO CLAIM: \"{claim}\"\nTest that claim against the samples. If "
               "the samples do not support it, say so plainly.\n" if claim else "")
            + (f"\nWHAT SHOULD BE PRESENT: {expected}\nFlag anything MISSING — absence is a defect, "
               "not a neutral.\n" if expected else "")
            + (f"\nCASE CONTEXT: {case[:300]}\n" if case else "")
            + f"\nSAMPLES ({len(rows)}):\n{blob}\n\n"
            "If you encounter something you have NO basis to judge — an artifact shape, a domain "
            "or a failure mode outside anything you can assess — do NOT guess a verdict. Put what "
            "you would need to know into \"questions\": the specific things a human should check. "
            "An honest question is worth more than a confident guess.\n\n"
            'Return STRICT JSON: {"flags": [{"kind": "short-slug", "why": "what fails in use", '
            '"sample": "the exact quote"}], "questions": ["what a human should check and why"], '
            '"uncertain": true|false, "claim_supported": true|false|null}', model=rmodel)
        if isinstance(data, dict):
            for f in (data.get("flags") or [])[:10]:
                if isinstance(f, dict) and str(f.get("why", "")).strip():
                    out["flags"].append({"kind": str(f.get("kind", "") or "judgment")[:40],
                                         "why": str(f["why"])[:300],
                                         "sample": str(f.get("sample", ""))[:200]})
            out["questions"] = [str(q).strip()[:220]
                                for q in (data.get("questions") or []) if str(q).strip()][:6]
            if data.get("uncertain"):
                out["flags"].append({"kind": "uncertain",
                                     "why": "reviewer could not determine whether this works — "
                                            "escalating rather than passing", "sample": ""})
                return out                            # escalate
            if data.get("claim_supported") is False and claim:
                out["flags"].append({"kind": "claim-unsupported",
                                     "why": f"the samples do not support the claim: {claim[:120]}",
                                     "sample": ""})
        else:
            return out                                # no usable verdict -> escalate
    except Exception:
        return out                                    # reviewer unavailable -> escalate, never pass

    out["verdict"] = "fail" if out["flags"] else "pass"
    return out


def course_correction(kind: str, result: dict, *, case: str = "", n: int = 2) -> list:
    """When the gate found the work drifting, propose ADDITIONAL questions that pull it back.

    Gambit, 2026-07-28: "can it course-correct if it senses the search is going in the wrong
    direction... could it substantially ADD to the investigation." ADD is the operative word and
    the whole safety argument. v15 is the case in point: 'What happened to Steven Garcia?' dragged
    in Kilmar Abrego Garcia — a different man, a different case — and the run spent ~109 findings
    there with nothing to pull it back. The gate SAW that failure class; it had no way to act.

    STRICTLY ADDITIVE (Noor). It never rewrites or deletes an existing question. A rewrite steers,
    and if it steers wrong the original is gone and you would never know it happened. An addition
    that turns out wrong costs one question; an addition that is right can save the run. The
    corrections are labelled in the trace so their value is judgable after the fact (Vera).

    Returns [] when there is nothing to correct — silence is the correct output for healthy work."""
    flags = result.get("flags") or []
    if not flags or result.get("verdict") == "pass":
        return []
    try:
        from .publisher_reviewer import synthesis_model, reviewer_model
        from .memory.gap_detector import _cheap_json
        from .search_queries import bad_question
        problems = "\n".join(f"- {f.get('kind')}: {str(f.get('why'))[:150]}" for f in flags[:6])
        drifted = "\n".join(f"- {str(f.get('sample'))[:180]}" for f in flags[:4] if f.get("sample"))
        data = _cheap_json(
            "You are the CHALLENGER. An investigation is drifting and you have diagnosed why. Write "
            f"AT MOST {n} ADDITIONAL questions that pull it back on course.\n\n"
            "You are NOT rewriting anything — the existing questions still run. You are adding the "
            "questions a lead investigator would insert on noticing the drift.\n"
            "If the problem is that work landed on the WRONG SUBJECT (a namesake, an unrelated "
            "case), your correction must pin the RIGHT one using a detail only they have — their "
            "employer, their city, their date. That is the highest-value correction available.\n"
            "RULES: under 12 words each, ONE question, name something specific, never ask whether a "
            "document exists. If nothing useful can be added, return an empty list — silence beats "
            "a filler question.\n\n"
            f"CASE: {case[:300]}\n\nWHAT THE GATE FOUND:\n{problems}\n\n"
            f"WHAT DRIFTED:\n{drifted or '(no samples)'}\n\n"
            'Return STRICT JSON: {"corrections": ["..."]}',
            model=reviewer_model(synthesis_model()))
        out = []
        for q in (data.get("corrections") or []) if isinstance(data, dict) else []:
            s = " ".join(str(q).strip().strip('"').split())
            # the corrector must obey the same rules it enforces — otherwise it injects the very
            # defect it exists to catch (this actually happened with an org template earlier today)
            # NO INVENTED ENTITIES (2026-07-28). The wiring dry-run caught the corrector proposing
            # "Which scientists disappeared from the Geneva research center?" and "What roles did
            # Dr. Lin and Dr. Saito hold?" — none of which exist in this case. With thin context it
            # fills in plausible specifics, and a correction naming a nonexistent lab sends real
            # fetches chasing nothing: the exact contamination this gate exists to PREVENT. So every
            # capitalised proper noun in a correction must already appear in the case or the samples.
            _grounded = (case + " " + " ".join(str(f.get("sample", "")) for f in flags)).lower()
            _caps = [w for w in re.findall(r"\b[A-Z][a-z]{2,}\b", s) if w.lower() not in _STOP_CAPS]
            _anchored = [w for w in _caps if w.lower() in _grounded]
            # A correction must be ANCHORED in something real from the case before it may add an
            # inference. "Was Steven Garcia last seen at Sandia National Labs?" is good — Garcia is
            # real, Sandia is a useful domain guess. "Which scientists vanished from the Geneva
            # research center?" is pure invention with nothing real in it. Requiring one grounded
            # entity keeps the useful inference and kills the fabrication, where blocking every
            # ungrounded noun killed both.
            if _caps and not _anchored:
                continue
            if s and not bad_question(s) and s.lower() not in {o.lower() for o in out}:
                out.append(s)
        return out[:n]
    except Exception:
        return []


def format_report(result: dict, title: str = "CHALLENGER") -> str:
    """Render a challenge result for humans. Always prints the SAMPLES — the display is the check,
    and a verdict without the evidence under it is exactly the summary-instead-of-artifact pattern
    that hid the question defect for fourteen runs."""
    v = result.get("verdict", "escalate")
    mark = {"pass": "PASS", "fail": "!! FAIL", "escalate": "?? ESCALATE — human review"}.get(v, v)
    lines = [f"— {title} — {mark}  ({result.get('n_checked', 0)} samples checked"
             + (f", reviewer: {result['reviewer_model']}" if result.get("reviewer_model") else "") + ")"]
    for f in (result.get("flags") or [])[:10]:
        lines.append(f"    ✗ {f.get('kind', '?')}: {f.get('why', '')[:150]}")
        if f.get("sample"):
            lines.append(f"        “{f['sample'][:120]}”")
    for q in (result.get("questions") or [])[:6]:
        lines.append(f"    ? {q[:150]}")
    if v == "pass" and not result.get("questions"):
        lines.append("    (no functional defects found — samples below for your own eyes)")
    for s in (result.get("samples") or [])[:6]:
        lines.append(f"      · {s[:120]}")
    return "\n".join(lines)
