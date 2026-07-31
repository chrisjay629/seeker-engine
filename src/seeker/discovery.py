"""Roster discovery (Gambit, 2026-07-21) — find the case subjects we were NEVER told about.

THE GAP THIS CLOSES. Seeker only ever VERIFIED names it was handed. The 2026-07-21 audit put it
bluntly: "Carl Grillmair isn't in the roster at all, and nothing in this inventory would have
discovered him." Worse, the director gated its only completeness check behind `if not seeds:` — so on
every seeded run (i.e. every real investigation we have done) discovery never executed at all. A
seeded roster is what the USER knows, not what is TRUE.

WHY A NAIVE VERSION IS DANGEROUS (the reason this is an organ and not a regex). The old check scraped
proper nouns out of findings and flagged anything unmatched as "missing from our roster". On this case
that sweeps up Marjorie Taylor Greene, an FBI commentator, journalists, and grieving relatives — and
labelling a living spokesperson a "missing/dead scientist" is a real harm, not a formatting bug
(Ghost/Mack). Viral lists also pad themselves with people who were never missing (Noor), so discovery
must not launder a conspiracy list into our roster.

SO: harvest candidates widely, then CLASSIFY each one against the findings that mention them, and keep
only those the evidence places as a CASE SUBJECT. Everything else is rejected WITH ITS REASON, so the
rejection is auditable rather than invisible. Survivors are returned as UNVERIFIED CANDIDATES — they
earn their own verification lead; they are never asserted as victims (Vera).
"""
from __future__ import annotations

from .memory.gap_detector import _reason_json
from . import synthesis as _synthesis
from .entity_resolution import proper_names

# Roles that are NOT case subjects. A name landing in one of these buckets must never be promoted.
_NON_SUBJECT = ("commentator", "official", "journalist", "politician", "relative",
                "investigator", "expert", "organization", "other")


# Tokens that mark an ORGANISATION/place/fragment rather than a person. Measured against a real
# candidate pool: without this, 'Los Alamos National Laboratory', 'House Oversight Committee',
# 'Capitol Police' and 'New Mexico Department' all compete for classifier attention.
_ORG_TOKENS = {"laboratory", "committee", "department", "agency", "police", "university", "office",
               "center", "centre", "institute", "administration", "bureau", "council", "house",
               "college", "hospital", "corporation", "company", "association", "foundation",
               "security", "propulsion", "county", "state", "force", "command", "division"}
_LEAD_STOP = {"the", "in", "on", "a", "an", "at", "of", "and", "public", "unidentified"}


def _plausible_person(name: str) -> bool:
    """Cheap structural gate: is this even shaped like a person's name? Filters organisations,
    possessives, sentence fragments, and duplicated-token garbage BEFORE the classifier sees them."""
    n = " ".join((name or "").split())
    if not n or n.endswith("'s") or "'" in n:
        return False
    toks = n.split()
    if not (2 <= len(toks) <= 4):                 # 'Reza' / 'Monica Jacinto Reza Reza' both out
        return False
    low = [t.lower().strip(".,") for t in toks]
    if low[0] in _LEAD_STOP:                      # 'The New Mexico Department', 'In July'
        return False
    if any(t in _ORG_TOKENS for t in low):        # organisation, not a person
        return False
    if len(set(low)) != len(low):                 # 'Monica Jacinto Reza Reza'
        return False
    return all(t[:1].isupper() for t in toks)     # every token capitalised


def _candidate_names(findings: list, known: set) -> dict:
    """{name -> mention count} for PERSON-shaped proper names in the corpus that aren't already known.
    `known` matching uses the entity resolver, so 'Monica A. Jacinto Reza' and 'Anthony William
    Chavez' collapse onto roster entries instead of being promoted as new people (and the known
    garble 'Melissa Cascio' cannot become a phantom 14th victim)."""
    from .entity_resolution import _same_entity
    counts: dict = {}
    for f in findings:
        claim = f.get("claim", "") if isinstance(f, dict) else getattr(f, "claim", "")
        for n in proper_names(claim):
            if not _plausible_person(n):
                continue
            low = " ".join(n.lower().split())
            if any(low in k or k in low or _same_entity(low, k) for k in known):
                continue
            counts[n] = counts.get(n, 0) + 1
    # collapse variants AMONG the candidates themselves — keep the longest spelling, sum the mentions
    merged: dict = {}
    for n, c in sorted(counts.items(), key=lambda kv: -len(kv[0])):
        hit = next((m for m in merged if _same_entity(n.lower(), m.lower())), None)
        if hit:
            merged[hit] += c
        else:
            merged[n] = c
    return merged


def discover_roster(subject: str, known_roster: list, *, branch_id: str = "main", mm=None,
                    top_k: int | None = None, min_mentions: int = 2, max_candidates: int = 12) -> dict:
    """Find CASE SUBJECTS absent from the known roster. Returns
      {"candidates": [{name, role, mentions, why, status_hint}],   # unverified, worth investigating
       "rejected":   [{name, role, why}],                          # auditable exclusions
       "considered": int}
    Grounded in gathered findings; never asserts anyone's status. Fail-open to empty."""
    known = {" ".join(str(k).lower().split()) for k in (known_roster or []) if str(k).strip()}
    try:
        buckets = _synthesis.gather_findings(subject, branch_id=branch_id, top_k=top_k, mm=mm)
        findings = []
        for label in ("well-supported", "contested", "unverified"):
            findings += buckets.get(label, [])
        if not findings:
            return {"candidates": [], "rejected": [], "considered": 0}

        counts = _candidate_names(findings, known)
        # a single passing mention is usually a byline or a quoted official — require corroboration
        cands = [n for n, c in sorted(counts.items(), key=lambda kv: -kv[1])
                 if c >= min_mentions][:40]
        if not cands:
            return {"candidates": [], "rejected": [], "considered": len(counts)}

        # give the classifier each candidate's OWN evidence (per-entity, not a global slice — the
        # lesson from the entity_profiles top_k bug)
        blocks = []
        for n in cands:
            low = n.lower()
            mine = [f.get("claim", "") for f in findings
                    if low in (f.get("claim", "") or "").lower()][:6]
            blocks.append(f"### {n} ({counts[n]} mentions)\n" + "\n".join(f"- {c}" for c in mine))
        prompt = (
            "You are building the ROSTER for an investigation: the people the case is ABOUT. For each "
            "candidate below, decide from THEIR OWN EVIDENCE what role they play.\n"
            "role must be exactly one of: case_subject | commentator | official | journalist | "
            "politician | relative | investigator | expert | organization | other\n"
            "  case_subject = a person the case is about — someone reported missing, dead, or whose "
            "status/fate is part of the investigation itself.\n"
            "  Everyone else (spokespeople, agency officials, reporters, politicians commenting, "
            "family members, named investigators, pundits) is NOT a case subject.\n"
            "HARD RULES: judge ONLY from the evidence shown. If the evidence does not clearly place a "
            "person as a subject of the case, do NOT mark them case_subject — say 'other'. NEVER infer "
            "that someone is missing or dead because they appear in a list alongside people who are; "
            "viral lists include people who were never missing. Give status_hint ONLY if the evidence "
            "states it (missing/deceased/unknown), else ''.\n\n"
            f"CASE: {subject}\n\nCANDIDATES:\n" + "\n\n".join(blocks) + "\n\n"
            'Return STRICT JSON: {"people": [{"name": "...", "role": "case_subject", '
            '"status_hint": "", "why": "<=12 words citing the evidence>"}]}')
        data = _reason_json(prompt)
        rows = (data.get("people") or []) if isinstance(data, dict) else []

        from .entity_resolution import _same_entity
        cands_out, rejected, seen_returned = [], [], set()
        for p in rows:
            if not isinstance(p, dict) or not p.get("name"):
                continue
            name = str(p["name"]).strip()
            role = str(p.get("role", "other")).strip().lower()
            # the classifier often returns a NORMALISED spelling ('William Robert Neil McCasland' for
            # candidate 'William Robert Neil'), which broke the mention lookup and let 0-mention names
            # through. Map back to the candidate it actually came from.
            src = next((c for c in cands if _same_entity(c.lower(), name.lower())
                        or c.lower() in name.lower() or name.lower() in c.lower()), None)
            if src:
                seen_returned.add(src)
            rec = {"name": name, "role": role, "mentions": counts.get(src or name, 0),
                   "why": str(p.get("why", ""))[:120]}
            if role == "case_subject" and rec["mentions"] >= min_mentions:
                rec["status_hint"] = str(p.get("status_hint", "")).strip()
                cands_out.append(rec)
            else:
                if role == "case_subject":
                    rec["why"] = f"below corroboration floor ({rec['mentions']} mentions) — {rec['why']}"
                rejected.append(rec)
        # anything the classifier DIDN'T return is a rejection, recorded so the filtering is auditable
        # rather than a silent drop (Vera: an invisible rejection is an unverifiable one).
        for c in cands:
            if c not in seen_returned:
                rejected.append({"name": c, "role": "not_returned", "mentions": counts.get(c, 0),
                                 "why": "classifier did not place this name as a case subject"})
        cands_out.sort(key=lambda r: -r["mentions"])
        return {"candidates": cands_out[:max_candidates], "rejected": rejected[:20],
                "considered": len(counts)}
    except Exception:
        return {"candidates": [], "rejected": [], "considered": 0}


def enumeration_queries(subject: str) -> list:
    """Search-native queries that surface ROSTER LISTS rather than one person. The old single query
    ('Complete authoritative list of ALL named individuals in: <subject>') was instruction-shaped and
    retrieved poorly; these are how a person actually searches for the full list."""
    from . import search_queries as _sq
    base = _sq.strip_instructions(subject)
    out = _sq.plan_queries(f"the full list of people named in: {base}", engine="web", n=4)
    return out or [base]
