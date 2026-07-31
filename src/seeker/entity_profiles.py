"""Entity profiles (Gambit, 2026-07-19) — turn the bare roster into a per-person mini-dossier.

The map listed 13 names with nothing attached. This organ gives each canonical entity a compact,
GROUNDED profile — status, cause/outcome, and a one-line case detail — drawn ONLY from the findings we
gathered. It reads the same corpus the synthesis does, in ONE batched call for the whole roster.

Guardrails (council):
  • Vera: every field comes from the findings; if the findings don't say, it is 'under investigation'
    / 'limited information' — never invented, never inferred beyond what a source states.
  • Ghost/Mack: report a documented cause/outcome factually; NEVER assert foul play, a suspect, or
    guilt. Where a case is officially undetermined, say exactly that. Names here are already public.
  • Noor: a person with thin coverage renders honestly as 'limited information', not a padded story.
Fail-open: any error returns empty profiles so the dossier/map still renders the plain roster.
"""
from __future__ import annotations

from .memory.gap_detector import _reason_json
from . import synthesis as _synthesis

# Display statuses — a small closed set so the map can badge them consistently.
_STATUSES = ("deceased", "missing", "found safe", "under investigation", "disputed", "unknown")


def _norm_status(s: str) -> str:
    s = (s or "").strip().lower()
    for k in _STATUSES:
        if k in s:
            return k
    if "dead" in s or "death" in s or "died" in s:
        return "deceased"
    if "disappear" in s or "vanish" in s:
        return "missing"
    return "unknown"


def _entity_keys(name: str) -> set:
    """Match keys for a person: the full name plus each distinctive token (surname/given), so
    'McCasland' and 'William Neil McCasland' both land. ONE canonical matcher — profiles, the
    depth-equalizer, and anything else counting per-person evidence must share it (Cipher: a second
    hand-rolled copy is how the orphaned-function drift happened)."""
    n = str(name or "").strip()
    return {n.lower()} | {t.lower() for t in n.split() if len(t) > 3}


def findings_per_entity(subject: str, entities: list, *, branch_id: str = "main", mm=None,
                        top_k: int | None = None) -> dict:
    """How much evidence each roster person actually has: {name: n_findings}. Fail-open to {}.

    This is the measurement behind depth equalization — an investigator gives the COLD case more
    attention, not less, but Seeker's wave-2 only deepened people who surfaced in connections, so
    well-covered names compounded while thin ones stalled (v9: McCasland 19 mentions vs Eskridge 2)."""
    names = [str(e).strip() for e in (entities or []) if str(e).strip()]
    if not names:
        return {}
    try:
        buckets = _synthesis.gather_findings(subject, branch_id=branch_id, top_k=top_k, mm=mm)
        findings = []
        for label in ("well-supported", "contested", "unverified"):
            findings += buckets.get(label, [])
        # COUNT ONLY EVIDENCE THAT IS ACTUALLY ABOUT THEM (2026-07-30). This counted raw surname
        # matches, which turned the equalizer into a contamination pump: it saw Matthew James
        # Sullivan's file was thin, spent extra leads filling it, and pulled in William Sullivan,
        # Lynne Sullivan and Sullivan County — then counted those as depth and concluded the gap was
        # closed. The v19 triage rejected 52 of Sullivan's 59 findings and 28 of Garcia's 59. The
        # organ built to help cold cases was feeding them the wrong person.
        # wrong_person() is deterministic and was validated against all 705 triaged verdicts:
        # 98% precision, one false positive. A miss just leaves a finding counted, which is the
        # safe direction — under-counting sends MORE attention to a thin person, never less.
        from .identity import wrong_person as _wrong
        out = {}
        for n in names:
            keys = _entity_keys(n)
            hits = [f for f in findings
                    if any(k in (f.get("claim", "") or "").lower() for k in keys)]
            out[n] = sum(1 for f in hits if not _wrong(f.get("claim", ""), n))
        return out
    except Exception:
        return {}


def entity_profiles(subject: str, entities: list, *, branch_id: str = "main", mm=None,
                    top_k: int | None = None, per_entity: int | None = None) -> list:
    """A grounded mini-dossier per canonical entity. Returns
    [{"name", "status", "cause", "detail"}] in the order given. One batched LLM call; fail-open to [].

    PER-ENTITY RETRIEVAL (fix 2026-07-21): this used to take a global top_k=70 slice and hope every
    person appeared in it. On a big corpus that silently FAILS — at 814 findings the 70-item window
    contained ZERO findings for Loureiro/Eskridge/Maiwald (all present at top_k=400), so people who
    profiled correctly on a smaller run regressed to 'unknown'. More findings made profiles WORSE.
    Now we pull a wide corpus ONCE and give each person their OWN evidence block, so no one can be
    crowded out by topical material."""
    names = [str(e).strip() for e in (entities or []) if str(e).strip()]
    if not names:
        return []
    try:
        buckets = _synthesis.gather_findings(subject, branch_id=branch_id, top_k=top_k, mm=mm)
        findings = []
        for label in ("well-supported", "contested", "unverified"):
            findings += buckets.get(label, [])
        if not findings:
            return [{"name": n, "status": "unknown", "cause": "",
                     "detail": "No findings gathered for this individual."} for n in names]
        # Build a PER-PERSON evidence block: findings whose claim mentions that person (match on the
        # full name or its surname, so 'McCasland'/'Neil' style variants still land).
        blocks, unmatched = [], []
        for n in names:
            keys = {n.lower()} | {t.lower() for t in n.split() if len(t) > 3}
            mine = [(f.get("claim", ""), float(f.get("corroboration", 1) or 1)) for f in findings
                    if any(k in (f.get("claim", "") or "").lower() for k in keys)]
            if mine:
                # PER-PERSON WINDOW REMOVED (2026-07-30). This showed the model the first 10
                # findings for each person. The SIXTH occurrence of the fixed-window class in this
                # project, and it was exposed by fixing the others: lifting the global retrieval cap
                # gave Michael David Hicks 15 findings instead of 11, which pushed "the Los Angeles
                # Medical Examiner's Office listed his cause of death as Arteriosclerotic
                # Cardiovascular Disease" to position 13 — outside the window. His profile lost a
                # documented cause BECAUSE more evidence arrived. This module's own docstring warns
                # about the previous instance of exactly this.
                # Ordered best-corroborated first so that if a budget is ever reintroduced, it cuts
                # by evidence strength rather than by arrival order.
                mine_sorted = sorted(mine, key=lambda c: -c[1])
                shown = [c for c, _ in (mine_sorted if per_entity is None
                                        else mine_sorted[:per_entity])]
                blocks.append(f"### {n}\n" + "\n".join(f"- {c}" for c in shown))
            else:
                unmatched.append(n)
                blocks.append(f"### {n}\n- (no findings mention this person)")
        blob = "\n\n".join(blocks)
        roster = "\n".join(f"- {n}" for n in names)
        prompt = (
            "For EACH person in the ROSTER, write a compact factual profile using ONLY the FINDINGS "
            "below. Fields per person:\n"
            "NAMESAKE GUARD: a person's findings may include a DIFFERENT individual who happens to share "
            "the name (e.g. an academic with an unrelated career whose papers were pulled in by a name "
            "search). Use ONLY findings consistent with THIS case (see SUBJECT); DISREGARD findings that "
            "clearly describe an unrelated same-named person. If the on-case findings are too few to "
            "establish status, say 'unknown' and explain it's a name-collision / thin record — never let "
            "a namesake's biography become this person's profile.\n"
            "- status: one of exactly [deceased, missing, found safe, under investigation, disputed, "
            "unknown] — what the findings establish about them.\n"
            "- cause: the documented cause of death or outcome IF the findings state one (e.g. 'heart "
            "attack', 'homicide', 'suicide', 'died in a house fire', 'still missing'); empty string if "
            "the findings do not state a cause.\n"
            "- detail: ONE-TO-TWO sentences of the most salient case specifics from the findings "
            "(role/employer, where/when last seen, official status). If status is 'unknown' or "
            "'disputed', the detail MUST explain WHY — e.g. the evidence is ambiguous, or the only "
            "status claims are unverified/contested — rather than saying 'no details'. When an "
            "unverified or conspiracy claim exists about the person, note that such a claim exists and "
            "that it is UNVERIFIED, but do NOT repeat the specific accusation against any named party.\n"
            "HARD RULES: use ONLY the findings — invent NOTHING. NEVER assert foul play, a suspect, or "
            "anyone's guilt, and NEVER set a factual status (deceased/missing) from an UNVERIFIED or "
            "conspiracy claim alone — such a claim keeps status 'unknown' or 'disputed'. If a cause is "
            "officially undetermined or contested, say so plainly. Only if the findings truly say "
            "nothing beyond a bare mention, use 'Limited information in the gathered findings.' Report a "
            "documented cause straight — do not soften it.\n\n"
            "The EVIDENCE below is grouped per person under a '### Name' heading — use each person's "
            "OWN block for their profile. A block reading '(no findings mention this person)' means we "
            "genuinely gathered nothing on them: set status 'unknown' and say so plainly.\n\n"
            f"SUBJECT (the case — use it to reject same-named strangers):\n{subject}\n\n"
            f"ROSTER:\n{roster}\n\nEVIDENCE (grouped by person):\n{blob}\n\n"
            'Return STRICT JSON: {"profiles": [{"name": "<exact roster name>", "status": "...", '
            '"cause": "...", "detail": "..."}]}')
        data = _reason_json(prompt)
        got = {}
        if isinstance(data, dict):
            for p in (data.get("profiles") or []):
                if isinstance(p, dict) and p.get("name"):
                    got[str(p["name"]).strip().lower()] = p
        out = []
        for n in names:
            p = got.get(n.lower(), {})
            out.append({
                "name": n,
                "status": _norm_status(p.get("status", "")),
                "cause": str(p.get("cause", "")).strip(),
                "detail": str(p.get("detail", "")).strip() or "Limited information in the gathered findings.",
            })
        return out
    except Exception:
        return []
