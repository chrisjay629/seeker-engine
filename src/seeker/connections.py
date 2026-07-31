"""The Connections Engine (Gambit, 2026-07-16) — Seeker's OWN cross-entity analysis.

The gap this closes: Seeker mostly RECITED what sources said ("the FBI found no link") instead of
deriving its own connections. On the missing-scientists case it had, in hand, that Monica Reza's
patent was developed with the Air Force Research Laboratory AND that William McCasland was AFRL's
former commander — two of thirteen, both tied to AFRL — and never flagged it, because it pulled each
name in isolation. This organ builds a RELATIONSHIP view over everything gathered and surfaces the
connections (or the honest ABSENCE of them) that no single finding states.

Two intended modes (brief 32, task #25):
  A. CONNECT-WHILE-GATHERING — cross-reference each new finding against the held map at extraction
     time (the deeper mode; follow-on — hooks extraction).
  B. ANALYSIS PASS (this file) — derive links over the accumulated corpus at synthesis time.

Hard guardrail (Vera/Ghost): surface REAL connections only, each traced to the findings that support
it; NEVER fabricate a link or imply a pattern the data doesn't support; a verified NON-connection is a
first-class result; connections are about evidence, never a person's guilt.
"""
from __future__ import annotations

import re

from .memory.gap_detector import _reason_json
from . import synthesis as _synthesis

# org/institution cues — SPECIFIC named institutions only. Generic tokens (inc/office/command/agency/
# department) and short ambiguous ones (cia matched noise) caused false co-occurrence "connections" in
# v1, so they're removed: a shared org must be a real, named employer/lab, not a generic word.
_ORG_CUES = ("laboratory", "university", "institute", "nasa", "jpl", "afrl", "los alamos", "sandia",
             "caltech", "livermore", "oak ridge", "national laboratory", "space flight center",
             "jet propulsion", "air force research", "plasma science")


from .entity_resolution import proper_names as _proper_names   # one canonical extractor (no drift)


def _orgs(text: str) -> set:
    """Organisation-ish tokens present in a finding (lowercased), by cue words."""
    t = (text or "").lower()
    return {c for c in _ORG_CUES if c in t}


def entity_index(findings: list) -> dict:
    """Pure, testable: {entity_name -> set(finding_indices)} + {org -> set(indices)} for co-occurrence.
    Returns {"names": {...}, "orgs": {...}}. No network."""
    names, orgs = {}, {}
    for i, f in enumerate(findings):
        claim = f.get("claim", "") if isinstance(f, dict) else getattr(f, "claim", "")
        for n in _proper_names(claim):
            names.setdefault(n, set()).add(i)
        for o in _orgs(claim):
            orgs.setdefault(o, set()).add(i)
    return {"names": names, "orgs": orgs}


def _shared_org_pairs(idx: dict) -> list:
    """Entities that co-occur with the SAME organisation across findings — the strongest cheap signal.
    Returns [{"org", "entities":[...]}] where >=2 distinct names share an org. Grounded in the index."""
    # map org -> set of names that appear in a finding mentioning that org
    org_names = {}
    for org, fidxs in idx["orgs"].items():
        for name, nidxs in idx["names"].items():
            if fidxs & nidxs:                      # the name and the org co-occur in a finding
                org_names.setdefault(org, set()).add(name)
    out = []
    for org, ns in org_names.items():
        if len(ns) >= 2:
            out.append({"org": org, "entities": sorted(ns)})
    return out


def find_connections(subject: str, *, branch_id: str = "main", mm=None, top_k: int | None = None) -> dict:
    """Derive Seeker's OWN connections over the gathered corpus. Returns
    {"connections":[{entities,link,basis}], "non_connections":[...], "shared_org_signals":[...]}.
    A cheap structural pass (shared-org co-occurrence) seeds an LLM pass that judges which links are
    REAL and reports honest non-connections. Fail-open. Grounded; never fabricates a link."""
    try:
        buckets = _synthesis.gather_findings(subject, branch_id=branch_id, top_k=top_k, mm=mm)
        findings = []
        for label in ("well-supported", "contested", "unverified"):
            findings += buckets.get(label, [])
        # KEYSTONE (#23): resolve entities FIRST so 'Monica Reza'/'Monica Jacinto Reza' are ONE person
        # and garbled spoken-only names (e.g. 'Schiavo') are flagged suspect, not analysed as real.
        from .entity_resolution import resolve_entities
        res = resolve_entities(findings)
        suspect = set(res.get("suspect_names", []))
        idx = entity_index(findings)
        signals = _shared_org_pairs(idx)             # structural hints, grounded
        blob = "\n".join(f"- {f.get('claim','')}" for f in findings)   # a link between two people is
        # exactly what hides outside a 70-finding window
        roster = ", ".join(c["canonical"] for c in res.get("entities", [])
                           if not c.get("suspect"))[:1200]
        susp_txt = ", ".join(sorted(suspect)[:20]) or "(none)"
        sig_txt = "\n".join(f"- shared '{s['org']}': {', '.join(s['entities'][:6])}"
                            for s in signals[:12]) or "(none detected structurally)"
        prompt = (
            "You are an intelligence analyst doing LINK ANALYSIS over verified case findings. Find "
            "genuine CONNECTIONS between the people/entities that NO single finding states outright — "
            "shared employer/lab/project, co-occurrence, overlapping dates, shared location, AND — "
            "added 2026-07-28 — SHARED RESEARCH SUBJECT: the same field, technology, program, "
            "funder, or scientific problem. Two people at the same lab is weak; two people "
            "working the same specific problem is a real link. The "
            "structural hints below (entities sharing an organisation) are candidates to check, not "
            "conclusions.\n"
            "HARD RULES: assert a connection ONLY if a finding states a REAL relationship (same "
            "employer/lab/project, worked together, direct tie) — a shared employer counts ONLY if "
            "BASE RATE (Noor/Vera, 2026-07-28): a shared field is only interesting when it is "
            "NARROWER than the population it is drawn from. 'Both were scientists', 'both at a "
            "national lab', 'both in aerospace' describe tens of thousands of people and are "
            "NOT connections — say so plainly rather than listing them. 'Both worked on the same "
            "named program / the same specific problem / the same funded contract' IS one. When a "
            "field is shared but common, report it as a NON-connection with the reason. Reporting "
            "an absence of pattern is a real finding, not a failure to find one. "
            "the findings actually place BOTH people there. Two names merely appearing in the same "
            "finding, or both mentioned in an investigation/news context, is NOT a connection — reject "
            "it. Do NOT connect a case subject to a commentator, official, statistician, or "
            "politician. Invent NOTHING; never imply a pattern the data doesn't support or anyone's "
            "ATTRIBUTION (2026-07-28, Ghost): when a link involves a crime or a death, phrase it "
            "exactly as strongly as the SOURCE does and say WHO says it. If the findings read "
            "'authorities connected X to the murder' or 'X is believed to have killed Y', write "
            "'authorities connected X to Y's murder' — NEVER flatten it to 'X murdered Y'. Seeker "
            "reports what officials and reporting establish; it does not pronounce guilt. A charge, "
            "an arrest, or an official finding is reportable AS SUCH, with the attributor named. "
            "guilt. When in doubt, it is a NON-connection. Report NON-CONNECTIONS you checked ('X and "
            "Y: no shared employer or project found') — a verified absence is a first-class result.\n\n"
            "Use the RESOLVED ROSTER as the canonical people/entities (variants already merged). Treat "
            "SUSPECT NAMES as likely transcription errors — do NOT assert connections about them.\n\n"
            f"CASE: {subject}\n\nRESOLVED ROSTER: {roster}\n\nSUSPECT NAMES (ignore / do not connect): "
            f"{susp_txt}\n\nSTRUCTURAL HINTS (entities sharing an org):\n{sig_txt}\n\n"
            f"FINDINGS:\n{blob}\n\n"
            # NON-CONNECTIONS MUST NAME BOTH PEOPLE (2026-07-30). Comparing v21 (70-finding window)
            # against v22 (all 431), the connection quality rose but the non-connections COLLAPSED
            # from eight specific pairs — "McCasland and Grillmair: checked, none found (no employer,
            # lab or project link)" — into four blanket lines like "Amy Eskridge and any other named
            # scientist: checked". The first is investigative output a reader can check. The second
            # is an assertion. With more evidence in view the model summarised instead of enumerating,
            # so the instruction now forbids the blanket form.
            'Return STRICT JSON: {"connections": [{"entities": ["A","B"], "link": "what connects them", '
            '"basis": "the finding(s) that support it"}], "non_connections": ["X and Y: checked, none '
            'found (reason)"]}\n'
            'NON-CONNECTION RULE: every entry must name TWO SPECIFIC PEOPLE from the roster and give '
            'the reason nothing links them. NEVER write "X and any other named individual" or "X and '
            'all scientists" — a blanket claim is not a check. Report the pairs you actually '
            'examined, one line each. An absence of connection between two named people is a real '
            'finding; a summary that no connections exist is not.')
        data = _reason_json(prompt)
        conns, nonconns = [], []
        if isinstance(data, dict):
            for c in (data.get("connections") or []):
                if isinstance(c, dict) and c.get("link"):
                    conns.append({"entities": [str(e) for e in (c.get("entities") or [])][:6],
                                  "link": str(c["link"]).strip(),
                                  "basis": str(c.get("basis", "")).strip()})
            nonconns = [str(x).strip() for x in (data.get("non_connections") or []) if str(x).strip()]
        return {"connections": conns[:15], "non_connections": nonconns[:12],
                "shared_org_signals": signals[:12],
                "resolved_entities": [c["canonical"] for c in res.get("entities", []) if not c.get("suspect")],
                "suspect_names": sorted(suspect)[:20]}
    except Exception:
        return {"connections": [], "non_connections": [], "shared_org_signals": [],
                "resolved_entities": [], "suspect_names": []}
