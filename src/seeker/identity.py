"""Identity anchoring (Gambit's design, 2026-07-29) — make Seeker prove it is reading about the
SAME PERSON before it keeps a finding.

THE PROBLEM. A name is not an identity. Searching "Joshua LeBlanc" returns every Joshua LeBlanc
alive or dead; searching "Carl Grillmair" returns an astrophysicist's citation pages alongside a
homicide report. Seeker had exactly one defence — a paragraph of PROSE in the entity_profiles
prompt telling the writer to "disregard findings that describe an unrelated same-named person."
By then the contaminated findings had already been embedded, counted toward coverage, fed to the
connections engine, and cited by Quill. Advice at the end of a pipeline cannot undo intake at the
start of it. (The standing lesson of this project: prose is advisory, code is binding.)

THE DESIGN, in two halves, because a name collision has to be fought at both ends:

  ASK BETTER — every person carries an IDENTITY CARD: role, employer, place, and years. The card's
  `disambiguator()` goes into their queries, so we ask for "Nuno Loureiro MIT plasma physicist"
  rather than "Nuno Loureiro". This is per-person. The run-scoped case anchor ("missing scientists")
  is shared by thirteen people and therefore distinguishes none of them from their own namesakes —
  worse, a shared anchor built from ONE person's details poisons the other twelve (v18: Seeker asked
  how Loureiro died in Albuquerque; he was shot in Brookline, Massachusetts — five leads returned 0).

  CHECK AFTER — every incoming claim is tested against the card. The YEAR test is DETERMINISTIC and
  binding: a claim that puts a death in 2019 cannot belong to a person the card has alive in 2025.
  No model is asked to be careful; the arithmetic decides. Softer signals (a conflicting employer, a
  conflicting city) are reported as WEAK and never hard-reject on their own, because people move,
  change jobs, and hold two affiliations at once.

WHAT A CONFLICT DOES: it QUARANTINES the finding and returns a tightened query, so the run
re-asks with a sharper anchor. It does NOT delete evidence silently and it does NOT halt the
investigation — the same rule the Challenger gate settled on. A quarantined finding is reported.

Guardrails: an EMPTY card blocks nothing (an unknown person must not have their real evidence
thrown away for failing to match facts we never learned). Every function fails open — on any error
the finding is kept and the reason recorded, because losing true evidence is worse than carrying a
suspect one we have flagged.
"""
from __future__ import annotations

import re as _re

# A card is: {"name", "role", "employer", "place", "born", "died", "notes"}
# born/died are ints or None. Everything else is a (possibly empty) string.

_YEAR = _re.compile(r"\b(1[89]\d{2}|20[0-4]\d)\b")

# Words that mark a year as belonging to the PERSON's lifespan rather than to some other event in
# the sentence ("founded in 1994", "the 2003 report"). Only years near these cues are trusted.
_DEATH_CUE = _re.compile(
    r"\b(died|death|deceased|killed|shot|murdered|homicide|fatally|passed away|body was found|"
    r"pronounced dead|disappeared|vanished|went missing|last seen|reported missing)\b", _re.I)
_BIRTH_CUE = _re.compile(r"\b(born|birth|date of birth|b\.)\b", _re.I)

# The namesake's giveaway: an appositive occupation right after the name — "Joshua LeBlanc, a wine
# tourism consultant, ..." Bounded to a short phrase so it captures the job title and not the rest
# of the sentence, and required to start with a/an/the so it is a DESCRIPTION of the person rather
# than an aside about something else.
_APPOSITIVE = _re.compile(r",\s+(?:an?|the)\s+([a-z][a-z\s\-]{3,44}?)\s*,", _re.I)

# How far apart a card year and a claim year may sit before we call it a conflict. A disappearance
# reported in December and confirmed dead in January is ONE event across two years — a 1-year slack
# absorbs that without absorbing a genuine 6-year mismatch.
_YEAR_SLACK = 1


def _years_near(text: str, cue: _re.Pattern, window: int = 60) -> set:
    """Years appearing within `window` characters of a cue word. Restricting by proximity is what
    separates 'died in 2011' from 'the 2011 budget' in the same paragraph."""
    out = set()
    for m in cue.finditer(text or ""):
        seg = text[max(0, m.start() - window): m.end() + window]
        out |= {int(y) for y in _YEAR.findall(seg)}
    return out


def blank_card(name: str) -> dict:
    return {"name": str(name or "").strip(), "role": "", "employer": "", "place": "",
            "born": None, "died": None, "notes": ""}


def disambiguator(card: dict, *, max_words: int = 6) -> str:
    """The distinguishing phrase appended to this person's queries.

    Ordered by discriminating power, which is NOT the same as by importance: an employer
    ('MIT Plasma Science and Fusion Center') pins a person far harder than a role ('physicist'),
    and a role pins harder than a city, since many people share a city and few share a lab. Kept
    short — search engines dilute a long query rather than sharpening it."""
    if not card:
        return ""
    bits = []
    for key in ("employer", "role", "place"):
        v = " ".join(str(card.get(key) or "").split())
        if v and v.lower() not in " ".join(bits).lower():
            bits.append(v)
    return " ".join(" ".join(bits).split()[:max_words])


def conflict(claim: str, card: dict) -> tuple:
    """Does this claim contradict the identity card? Returns (verdict, reason).

    verdict is one of:
      "ok"      — nothing contradicts the card (INCLUDING the empty-card case: we know nothing,
                  so we object to nothing)
      "hard"    — a YEAR contradiction. Arithmetic, not judgment. Quarantine it.
      "weak"    — employer/place disagree. Reported, never rejected alone: people relocate, hold
                  joint appointments, and are described by a former employer all the time.

    Deliberately NOT a model call. The whole point is that this verdict cannot be talked out of."""
    try:
        text = str(claim or "")
        if not text.strip() or not card:
            return ("ok", "")
        # --- HARD: year contradiction -------------------------------------------------
        for key, cue, label in (("died", _DEATH_CUE, "death/disappearance"),
                                ("born", _BIRTH_CUE, "birth")):
            known = card.get(key)
            if not known:
                continue
            found = _years_near(text, cue)
            if found and all(abs(int(y) - int(known)) > _YEAR_SLACK for y in found):
                return ("hard", f"{label} year {sorted(found)} conflicts with known {known}")
        # --- WEAK: the claim ASSERTS a different profession -----------------------------
        # Requires a POSITIVE contradiction, never a mere absence. The first cut of this checked
        # "claim doesn't mention the known employer" and flagged every true statement in the test
        # set ("was shot near his Massachusetts home" mentions no employer — nor should it). Absence
        # of a fact is not evidence of a different person; only an incompatible ASSERTION is.
        # The namesake's tell is an appositive occupation — "Joshua LeBlanc, a wine tourism
        # consultant," / "Nuno Loureiro, a Portuguese footballer," — so that is what we look for,
        # and we only object when it shares no meaningful word with what we know they did.
        known_work = f"{card.get('role') or ''} {card.get('employer') or ''}".lower()
        known_words = {w for w in _re.findall(r"[a-z]{4,}", known_work)}
        if known_words:
            for m in _APPOSITIVE.finditer(text):
                stated = m.group(1).lower()
                stated_words = {w for w in _re.findall(r"[a-z]{4,}", stated)}
                if stated_words and not (stated_words & known_words):
                    return ("weak", f"claim calls them '{m.group(1).strip()}'; "
                                    f"known as '{(card.get('role') or card.get('employer'))}'")
        return ("ok", "")
    except Exception as e:                      # fail open — never lose evidence to a bug here
        return ("ok", f"check failed: {e}")


# Words that turn a surname into a PLACE or INSTITUTION rather than a person: "Sullivan County",
# "Garcia Street". A different class of collision from a namesake, and just as common.
_NOT_A_PERSON = _re.compile(
    r"\b(county|city|street|avenue|road|drive|boulevard|park|school|university|college|hospital|"
    r"institute|center|centre|foundation|library|bridge|lake|river|township|district|precinct|"
    r"stadium|airport)\b", _re.I)


# Capitalised words that precede a surname without being a given name. Two kinds, both found by
# checking the check against 705 real verdicts rather than by imagining what it would hit:
# SENTENCE OPENERS ("When McCasland's wife returned...") and TITLES ("General McCasland", which is
# how the sheriff's office actually refers to him).
_NOT_A_GIVEN_NAME = {
    "the", "when", "during", "after", "before", "while", "since", "although", "though", "because",
    "however", "meanwhile", "later", "earlier", "then", "his", "her", "their", "this", "that",
    "mr", "mrs", "ms", "dr", "prof", "professor", "gen", "general", "maj", "major", "col",
    "colonel", "sgt", "sergeant", "lt", "lieutenant", "capt", "captain", "rep", "sen", "senator",
    "officer", "detective", "judge", "sheriff", "agent", "chief", "director", "president",
}

# A relation word means a named relative is being IDENTIFIED, not that the claim changed subject.
_FAMILY = _re.compile(
    r"\b(wife|husband|widow|widower|spouse|father|mother|son|daughter|brother|sister|parents?|"
    r"sibling|nephew|niece|uncle|aunt|cousin|in-law|family|survived by)\b", _re.I)


def wrong_person(claim: str, full_name: str) -> str:
    """Is this claim about a DIFFERENT person who shares the surname? Returns a reason, or "".

    Deterministic, and aimed at what actually went wrong rather than what sounded likely. The v19
    triage rejected 52 of Matthew James Sullivan's 59 findings and 28 of Steven Garcia's 59 — and
    reading them, the dominant failure was NOT the "Sullivan County" case I first assumed. It was a
    DIFFERENT GIVEN NAME on the same surname: William Sullivan, Lynne Sullivan, Christian Garcia,
    Melanie Garcia, Jose Ernesto Garcia, Jonathan Garcia.

    So the rule is: a given name immediately before the surname that is NOT one of this person's
    own given names means a different person. A bare surname with no given name is left ALONE —
    it is genuinely ambiguous, and guessing there would throw away real evidence, which is the
    expensive mistake."""
    name = " ".join(str(full_name or "").split())
    if not name:
        return ""
    parts = name.split()
    surname = parts[-1]
    given = {p.lower() for p in parts[:-1]}
    text = str(claim or "")
    low = text.lower()
    # If the person's OWN given name is in the claim, the claim is about them — a relative named
    # alongside them is not a namesake. "Louise Grillmair, widow of Carl Grillmair" is a fact about
    # Carl. This alone cleared three of the eight false positives found against the v19 verdicts.
    if any(g in low for g in given):
        return ""
    # A family relation anywhere in the sentence means the other name is a spouse/parent/child
    # being identified, not a different subject: "McCasland's wife, Susan McCasland Wilkerson".
    if _FAMILY.search(text):
        return ""
    for m in _re.finditer(r"\b([A-Z][a-z]{2,})\s+(?:[A-Z][a-z]*\.?\s+)?" + _re.escape(surname) + r"\b",
                          text):
        first = m.group(1).lower()
        if given and first not in given and first not in _NOT_A_GIVEN_NAME:
            return f"'{m.group(0)}' — different given name (this is {name})"
    # surname used as a place/institution: "Sullivan County", "Garcia Street"
    for m in _re.finditer(_re.escape(surname) + r"\s+(\w+)", text):
        if _NOT_A_PERSON.fullmatch(m.group(1) or ""):
            return f"'{m.group(0)}' — a place/institution, not {name}"
    return ""


def screen(findings: list, card: dict) -> tuple:
    """Split findings into (kept, quarantined) against one person's card.

    Only HARD (year) conflicts quarantine. Weak signals ride along on the kept finding as a note so
    a human — or Quill — can see the doubt without the evidence having been destroyed."""
    kept, quarantined = [], []
    for f in findings or []:
        claim = f.get("claim", "") if isinstance(f, dict) else str(f)
        verdict, reason = conflict(claim, card)
        if verdict == "hard":
            rec = dict(f) if isinstance(f, dict) else {"claim": claim}
            rec["quarantine_reason"] = reason
            quarantined.append(rec)
        else:
            rec = dict(f) if isinstance(f, dict) else {"claim": claim}
            if verdict == "weak":
                rec["identity_note"] = reason
            kept.append(rec)
    return kept, quarantined


def retry_queries(card: dict, *, angles: list | None = None, max_q: int = 4) -> list:
    """The RECONSTRUCTED search after a quarantine — the person's name pinned to their own
    distinguishing facts, plus the years when we have them. This is the 'ask again, but sharper'
    half of the loop; without it a quarantine only subtracts."""
    name = str((card or {}).get("name") or "").strip()
    if not name:
        return []
    dis = disambiguator(card)
    yr = card.get("died") or card.get("born") or ""
    base = " ".join(x for x in (name, dis, str(yr) if yr else "") if x).strip()
    out = [base] + [f"{base} {a}".strip() for a in (angles or
                    ["obituary", "cause of death", "last seen"])]
    seen, uniq = set(), []
    for q in out:
        k = " ".join(q.lower().split())
        if k and k not in seen:
            seen.add(k)
            uniq.append(" ".join(q.split()))
    return uniq[:max_q]


_CARD_PROMPT = (
    "Build an IDENTITY CARD for each person in the ROSTER, using ONLY the FINDINGS below.\n"
    "The card's job is to tell this person APART FROM A STRANGER WHO SHARES THEIR NAME. So prefer "
    "the facts that would differ between two same-named people: their employer or lab, their "
    "specific role, the city their case belongs to, and the year they died or disappeared.\n"
    "Fields per person: name, role, employer, place, born (4-digit year or null), "
    "died (4-digit year or null — use the year they died OR disappeared), notes (<=12 words).\n"
    "HARD RULES: take every field from the findings — invent NOTHING, infer NOTHING. A field you "
    "cannot support goes to empty string (or null for years). An EMPTY card is correct and useful; "
    "a GUESSED card is worse than none, because a wrong year will quarantine that person's real "
    "evidence. If findings about a person clearly describe two DIFFERENT individuals, card the one "
    "consistent with the SUBJECT and put 'name collision in sources' in notes.\n"
    "Return JSON: {\"cards\": [{...}, ...]} in roster order."
)


def build_cards(subject: str, entities: list, *, branch_id: str = "main", mm=None,
                top_k: int | None = None, per_entity: int = 10) -> dict:
    """{name: card} for the roster, grounded in the findings we already hold. Fail-open to blank
    cards — a run must never lose its identity checking to a bad LLM response, it just falls back
    to checking nothing, which is exactly where we were before this organ existed."""
    names = [str(e).strip() for e in (entities or []) if str(e).strip()]
    if not names:
        return {}
    cards = {n: blank_card(n) for n in names}
    try:
        from .memory.gap_detector import _reason_json
        from . import synthesis as _synthesis
        from .entity_profiles import _entity_keys

        buckets = _synthesis.gather_findings(subject, branch_id=branch_id, top_k=top_k, mm=mm)
        findings = []
        for label in ("well-supported", "contested", "unverified"):
            findings += buckets.get(label, [])
        if not findings:
            return cards
        blocks = []
        for n in names:
            keys = _entity_keys(n)
            mine = [f.get("claim", "") for f in findings
                    if any(k in (f.get("claim", "") or "").lower() for k in keys)]
            blocks.append(f"### {n}\n" + ("\n".join(f"- {c}" for c in mine[:per_entity])
                                          if mine else "- (no findings mention this person)"))
        data = _reason_json(
            _CARD_PROMPT + f"\n\nSUBJECT: {subject}\n\nROSTER:\n"
            + "\n".join(f"- {n}" for n in names)
            + "\n\nFINDINGS:\n" + "\n\n".join(blocks)) or {}
        for row in (data.get("cards") or []):
            nm = str(row.get("name") or "").strip()
            match = next((n for n in names if n.lower() == nm.lower()), None)
            if not match:
                continue
            c = cards[match]
            for k in ("role", "employer", "place", "notes"):
                c[k] = " ".join(str(row.get(k) or "").split())
            for k in ("born", "died"):
                v = row.get(k)
                try:
                    v = int(str(v)[:4])
                    c[k] = v if 1800 < v < 2050 else None
                except (TypeError, ValueError):
                    c[k] = None
    except Exception:
        pass
    return cards


def format_cards(cards: dict) -> str:
    """One line per person for the live log — so a wrong card is visible DURING the run, while it
    can still be corrected, rather than being discovered in the finished report."""
    if not cards:
        return "— IDENTITY CARDS — none"
    out = ["— IDENTITY CARDS (what pins each person apart from their namesakes) —"]
    for n, c in cards.items():
        dis = disambiguator(c) or "(nothing distinguishing — namesake risk HIGH)"
        yrs = "-".join(str(c.get(k) or "?") for k in ("born", "died"))
        out.append(f"  {n[:32]:32s} {dis[:46]:46s} {yrs}")
    return "\n".join(out)
