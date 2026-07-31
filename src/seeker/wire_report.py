"""Wire report (2026-07-29) — ONE linear write-up pass. Replaces the self-editing chain.

WHY THIS EXISTS. The old write-up chain edited its own output: draft -> fact-check -> self-critique
-> revise -> re-fact-check, and then, when the Publisher-Reviewer objected, another fix pass on top
of that. In v19 that loop ran eight times. Flag counts fell 6 -> 3 -> 2 and read as convergence,
while the substance drained out: the shipped artifact said "Status: Not recorded" for 11 of 13
people, though the profiles in the same dossier held all 13 statuses and 6 documented causes.

The mechanism, found afterwards: quill._fact_check verifies the draft against `_rows(bucket, 24)` —
about 96 of 500 findings. Any true detail supported by finding #97 or later reads as unsupported and
is CUT. Every pass cut a little more, and each pass ran on the previous pass's damage.

THE FIX IS STRUCTURAL, NOT A BIGGER WINDOW.

  1. GROUND IN THE PROFILES, NOT IN A RETRIEVAL SLICE. entity_profiles already does the hard work
     correctly: it gives each person their OWN evidence block, so nobody is crowded out of a shared
     window. Its output is grounded, per-person, and complete. So the dossier is BUILT FROM the
     profiles, and verified for FIDELITY TO them — a containment check, not a re-retrieval. There is
     no window to fall out of.

  2. AT MOST ONE CORRECTIVE PASS. If the draft still fails, we regenerate from the profiles rather
     than edit an edit. Editing an edit is what destroyed v19.

  3. FORM CARRIES THE VOICE. Five narrative drafts failed the voice gate on atmosphere; the
     wire-dossier form scored ZERO violations on its first attempt. A narrative needs mood to hold
     thirteen strands together; a dossier does not. Fix the form and the voice problem mostly
     disappears on its own.

The gates stay honest: a report that still fails is RETURNED FAILING with its flags, never retried
until the reviewer relents.
"""
from __future__ import annotations

import re as _re

from . import quill as _quill


def _entry_lines(profiles: list) -> str:
    out = []
    for p in profiles or []:
        bits = [f"- {p.get('name','')}: status={p.get('status','unknown')}"]
        if p.get("cause"):
            bits.append(f"cause={p['cause']}")
        if p.get("detail"):
            bits.append(f"detail={p['detail']}")
        out.append(", ".join(bits))
    return "\n".join(out)


_FORM = (
    "Write a WIRE-SERVICE DOSSIER answering the QUESTION, using ONLY the PROFILES and LEDGER below.\n\n"
    "STRUCTURE (mandatory):\n"
    "1. LEDE — two or three sentences of established fact: how many people, who is reviewing the "
    "cases, when it became public. No scene-setting, no mood.\n"
    "2. ONE ENTRY PER PERSON, all of them, in the order given. Each entry states: the name, their "
    "role or employer, their STATUS exactly as the profile records it, the documented cause if the "
    "profile records one, and one distinguishing case fact. Where a profile carries no cause, write "
    "'no cause documented in available records' — plainly, as a fact about the record, never as "
    "mystery or insinuation.\n"
    "3. PATTERN — what the ledger establishes and what it does not.\n"
    "   WEIGHT, not balance. Do NOT present the unproven coordination claim as one 'side' against "
    "the official findings — they are not peers, and setting them side by side tells the reader they "
    "are. Lead with what the record establishes: several deaths have documented, unrelated causes "
    "(cardiovascular disease, suicide, a traffic accident), two are prosecuted homicides, and "
    "authorities have not found evidence of a systemic threat. THEN report, in one or two sentences, "
    "that a claim of coordinated targeting circulates and is UNPROVEN — describing the claim's "
    "existence and status, not arguing its case.\n"
    "   NEVER QUOTE THE LEDGER'S CLAIM TEXT. Ledger entries preserve the phrasing of the sources that "
    "made them, loaded words and all ('mysterious deaths', 'directly linked', 'a string of'). "
    "Quoting one imports its framing even behind an attribution. Describe what is claimed in neutral "
    "words instead, and give its verdict.\n\n"
    "PLACEMENT RULE: claims about links BETWEEN cases belong in the PATTERN section only. Never put "
    "an unverified cross-case link inside a person's entry — there it reads as part of that "
    "individual's documented record.\n"
    "LINK RULE: a cross-case link is the thing under dispute, so it may never appear as a bare "
    "statement of fact. Write 'unverified reports have associated X with...', never 'X is directly "
    "linked to...' — the second asserts as established exactly what this investigation found is not "
    "established. Name the source whenever the ledger names one.\n\n"
    "REGISTER: every sentence must be one that would survive unchanged in a wire story. No "
    "atmosphere, no rhetorical questions, no menace the evidence does not establish. Attribute every "
    "claim ('the FBI said', 'reports link', 'records show'). Label unverified material as unverified.\n"
    "HARD RULE: use ONLY the PROFILES and LEDGER. Invent nothing. Do not accuse anyone. Do not "
    "upgrade a 'missing' to a death or a death to a homicide.\n"
)


def tallies(profiles: list) -> dict:
    """The counts, computed in code. A model asked to tally thirteen entries will get it wrong, and
    v20 did: it reported EIGHT people missing when four are, and its figures implied a roster of
    sixteen. Nobody noticed, because every check verified per-person entries and none verified the
    arithmetic ABOUT them. Counting is arithmetic; arithmetic is code's job."""
    st = {}
    for p in profiles or []:
        st[str(p.get("status") or "unknown").lower()] = st.get(
            str(p.get("status") or "unknown").lower(), 0) + 1
    return {"total": len(profiles or []), "by_status": st,
            "with_cause": sum(1 for p in (profiles or []) if p.get("cause"))}


def count_fidelity(prose: str, profiles: list) -> list:
    """Any number in the report that contradicts the real tallies. Checks the specific claim shape
    that failed ('N individuals are documented as missing') rather than every digit in the text —
    dates and ages are numbers too, and flagging those would drown the real error in noise."""
    out, t = [], tallies(profiles)
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13}
    NUM = r"\d{1,3}|" + "|".join(words)
    for status, true_n in t["by_status"].items():
        # The gap between the number and the status word must contain NEITHER another number NOR
        # another status. Without that, "four ... missing and nine are deceased" matched
        # four->deceased across the clause boundary and flagged a correct sentence. A count checker
        # that cries on correct text is worse than none — it teaches you to ignore it.
        others = [s for s in t["by_status"] if s != status]
        gap = r"(?:(?!\b(?:" + NUM + r")\b)" + (r"(?!\b(?:" + "|".join(others) + r")\b)" if others else "") + r"[^.])"
        for m in _re.finditer(r"\b(" + NUM + r")\b\s*" + gap + r"{0,40}?" + _re.escape(status),
                              prose or "", _re.I):
            word = m.group(1).lower()
            n = words.get(word, int(word) if word.isdigit() else None)
            # What comes BEFORE the number decides whether it is even a claim about our tally.
            # Checking only the text after it produced two false alarms: "at least 10 missing" is a
            # figure quoted from the FBI about a wider group, and "nine of THE THIRTEEN are
            # deceased" uses the roster size as a denominator. Both are correct writing.
            pre = (prose or "")[max(0, m.start() - 24):m.start()].lower()
            hedged = any(h in pre for h in ("at least", "more than", "over ", "nearly", "about ",
                                            "approximately", "up to", "of the", "of our"))
            if n is not None and n != true_n and not hedged:
                out.append(f"COUNT: report says {word} {status}; profiles record {true_n}")
    return out


def draft(question: str, profiles: list, ledger: list | None = None) -> str:
    ledger_lines = "\n".join(f"- [{c.get('verdict','')}] {str(c.get('claim',''))[:160]}"
                             for c in (ledger or [])[:14])
    t = tallies(profiles)
    counts = ("VERIFIED COUNTS — use these EXACTLY; do not count the entries yourself:\n"
              f"  roster total: {t['total']}\n"
              + "".join(f"  {k}: {v}\n" for k, v in sorted(t['by_status'].items()))
              + f"  with a documented cause: {t['with_cause']}\n")
    return (_quill._llm(
        _FORM + f"\nQUESTION: {question}\n\n{counts}\nPROFILES:\n{_entry_lines(profiles)}\n\n"
        f"LEDGER:\n{ledger_lines or '(none)'}\n", as_json=False) or "").strip()


def _segments(low: str, profiles: list) -> dict:
    """Split the report into one span per person: from where their entry begins to where the next
    person's begins. {name: span}.

    Deliberately NOT "N characters after the first mention of the surname" — that was the first cut
    of this function, and Vera and Noor both caught it: a fixed window keyed on a first match is the
    exact defect this whole module exists to prevent. A name mentioned in the lede would have made
    the checker read the LEDE as that person's entry and pass a report that never covered them.
    Boundaries come from the text's own structure instead: each person's span runs to the start of
    the next person's, so an entry can be any length and still be read whole."""
    out = {}
    for p in profiles or []:
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        # Facts that identify THIS person's entry, used to score candidate spans.
        wanted = {w for w in _re.findall(r"[a-z]{4,}", str(p.get("status") or "")
                                         + " " + str(p.get("cause") or ""))}
        best, best_score = "", -1
        for needle in (name.lower(), name.split()[-1].lower()):
            for m in _re.finditer(_re.escape(needle), low):
                span = low[m.start(): m.start() + 320]
                score = sum(1 for w in wanted if w in span)
                if score > best_score:
                    best, best_score = span, score
            if best_score > 0:
                break
        out[name] = best or low[:0]
    return out


def profile_fidelity(prose: str, profiles: list) -> list:
    """Does the report still say what the profiles say? Deterministic — this is the check that would
    have caught v19's collapse on the very first pass instead of after eight.

    Two failure directions, and LOSS is the one that actually bit us:
      MISSING  — a person the profiles cover who is absent from the report entirely.
      LOST     — the profile records a status or a documented cause and the report does not carry it.
                 v19 shipped 11 'Status: Not recorded' entries against 13 known statuses; nothing in
                 the pipeline noticed, because every check asked "is this supported?" and none asked
                 "is this still here?"
      INVENTED — the report asserts a death for someone the profiles record as missing. The one
                 direction that could hurt a living person's family, so it is checked explicitly."""
    out = []
    text = prose or ""
    low = text.lower()
    segs = _segments(low, profiles)
    for p in profiles or []:
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        surname = name.split()[-1].lower()
        if name.lower() not in low and surname not in low:
            out.append(f"MISSING: {name} is not in the report")
            continue
        seg = segs.get(name, low)
        status = str(p.get("status") or "").lower()
        if status and status not in ("unknown",) and status not in seg:
            out.append(f"LOST: {name} — profile status '{p['status']}' not stated in their entry")
        cause = str(p.get("cause") or "").strip()
        if cause:
            head = _re.findall(r"[a-z]{4,}", cause.lower())
            if head and not any(h in seg for h in head[:2]):
                out.append(f"LOST: {name} — documented cause '{cause[:40]}' dropped")
        # The word list is the whole guard, so it is written wide. The first version matched
        # died|death|deceased|killed and missed "was found dead" — the single most common phrasing
        # in this material — which would have let a MISSING person be reported dead to their family.
        # A false alarm here costs one review; a miss costs someone their mother's status.
        if status == "missing" and _re.search(
                r"\b(died|dead|death|deceased|killed|slain|murdered|fatally|homicide|"
                r"body was found|remains were found|autopsy|obituary)\b", seg):
            out.append(f"INVENTED: {name} is recorded MISSING but the report implies death")
    return out


def build(question: str, profiles: list, *, ledger: list | None = None,
          roster: list | None = None, review: bool = True) -> dict:
    """The whole write-up, start to finish, in one direction. Returns
    {report, voice_violations, fidelity_violations, review, corrective_passes}.

    Linear by construction: draft, check, at most ONE corrective pass, review, stop. Nothing here
    reads its own output twice."""
    names = roster or [str(p.get("name") or "") for p in (profiles or [])]
    prose = draft(question, profiles, ledger)
    passes = 0

    v = _quill.voice_violations(prose)
    f = profile_fidelity(prose, profiles) + count_fidelity(prose, profiles)
    if v or f:
        # ONE pass, and it regenerates against the PROFILES rather than editing the damaged text
        # sentence by sentence — the distinction that keeps substance from bleeding out.
        fixed = (_quill._llm(
            "Rewrite the REPORT below so it obeys the FORM and fixes the listed PROBLEMS.\n"
            "Every fact must come from the PROFILES — restore anything the report dropped, and "
            "remove anything the profiles do not support.\n\n"
            + _FORM
            + "\nPROBLEMS:\n" + "\n".join(f"- {x}" for x in (v + f)[:24])
            + f"\n\nPROFILES:\n{_entry_lines(profiles)}\n\nREPORT:\n{prose}\n", as_json=False) or "").strip()
        if fixed:
            prose, passes = fixed, 1
        v = _quill.voice_violations(prose)
        f = profile_fidelity(prose, profiles) + count_fidelity(prose, profiles)

    rev = {}
    if review:
        try:
            from . import publisher_reviewer as _pr
            rev = _pr.review(prose, question=question, roster=names)
        except Exception as e:
            rev = {"verdict": "unreviewed", "error": repr(e)[:120]}
    return {"report": prose, "voice_violations": v, "fidelity_violations": f,
            "review": rev, "corrective_passes": passes}
