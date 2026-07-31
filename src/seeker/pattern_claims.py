"""The Pattern-Claim Adjudicator (Gambit, 2026-07-19) — Seeker's answer to "who thinks they found a pattern?"

The gap this closes: when Seeker concludes "no coordinated pattern," that verdict was mostly *our own*
link analysis coming up empty — it never systematically hunted down the people CLAIMING a pattern and
ruled on their specific claims. Absence of evidence in our search is not the same as testing the claim.
This organ does the rigorous move: actively seek the claim side, take the STRONGEST version of each
claimed pattern (steelman), atomize it into discrete testable links, cross-check each link against the
FACTUAL record we gathered (the claim-ledger + the Connections Engine), and verdict it.

It fires on ANY subject, but it will most often meet conspiracies — which is fine: a conspiracy is just
people who feel they found a pattern. Some claims are junk; some are unproven yet worth noting (a claim
may be unproven only because an investigation was shut down, records sealed, or evidence lost). So the
verdict set extends the four-label standard with a fifth bucket Gambit asked for:

  supported · debunked · unverified · UNRESOLVED-NOTABLE (kept, with WHY it matters / why it's unproven)

Hard guardrails (council):
  • Vera: every verdict traces to findings; steelman is presentation, NOT endorsement.
  • Ghost/Mack: claims implicate living people — adjudicate the CLAIM, never assert a person's guilt;
    name a person only when already public; honor family opt-outs in substance.
  • Noor: flag patterns manufactured by selection bias (cherry-picked seed cases).
  • Cipher: cross-reference each claimed link against the confirmed claim-ledger + Connections links.
Fail-open: any error returns an empty, well-formed result so the flagship run never breaks.
"""
from __future__ import annotations

from .memory.gap_detector import _reason_json
from . import synthesis as _synthesis

# The fifth bucket is the whole point — keep it explicit so the map/ledger/Quill all agree on the label.
VERDICTS = ("supported", "debunked", "unverified", "unresolved-notable")


def _norm_verdict(v: str) -> str:
    v = (v or "").strip().lower().replace("_", "-")
    if v in VERDICTS:
        return v
    if "support" in v or "confirm" in v:
        return "supported"
    if "debunk" in v or "false" in v or "disprov" in v or "refut" in v:
        return "debunked"
    if "notable" in v or "unresolved" in v or "open" in v:
        return "unresolved-notable"
    return "unverified"


def adjudicate_claimed_patterns(subject: str, *, branch_id: str = "main", mm=None,
                                connections: dict | None = None, claim_ledger: list | None = None,
                                top_k: int | None = None) -> dict:
    """Find who claims a pattern, steelman each claim, atomize it, and verdict every asserted link
    against the factual record. Returns:
      {"claimed_patterns": [{pattern, claimants:[{who,credibility}], atomic_links:[{link,verdict,basis}],
                             verdict, why_notable, why_unproven, connects_to_factual}],
       "folded_count": int,          # low-signal fringe claims collapsed to a count (kept honest)
       "selection_bias_flags": [str],
       "counts": {verdict: n}}
    Grounded; never fabricates a claim or asserts anyone's guilt. Fail-open."""
    try:
        buckets = _synthesis.gather_findings(subject, branch_id=branch_id, top_k=top_k, mm=mm)
        # Claims live disproportionately in the UNVERIFIED / spoken-word bucket — that's where the
        # conspiracy material lands — so we deliberately include it here (unlike a facts-only pass).
        findings = []
        for label in ("well-supported", "contested", "unverified"):
            findings += buckets.get(label, [])
        if not findings:
            return _empty()
        claim_blob = "\n".join(f"- {f.get('claim','')}" for f in findings)   # this organ answers the
        # second half of the case question; it was doing so from 21% of the evidence

        # The FACTUAL yardstick to check claims against (Cipher / Gambit's #2): the confirmed links from
        # the Connections Engine + the well-supported claim-ledger entries. A claimed link is only
        # "supported" if it squares with THIS.
        conf_links = []
        for c in (connections or {}).get("connections", [])[:15]:
            ents = " & ".join(c.get("entities", []))
            conf_links.append(f"{ents}: {c.get('link','')}")
        nonlinks = (connections or {}).get("non_connections", [])[:12]
        facts = []
        for cl in (claim_ledger or [])[:25]:
            claim = cl.get("claim", "") if isinstance(cl, dict) else str(cl)
            label = cl.get("label", "") if isinstance(cl, dict) else ""
            if claim:
                facts.append(f"[{label}] {claim}")
        conf_txt = "\n".join(f"- {x}" for x in conf_links) or "(no confirmed links)"
        non_txt = "\n".join(f"- {x}" for x in nonlinks) or "(none)"
        facts_txt = "\n".join(f"- {x}" for x in facts) or "(no ledgered facts)"

        prompt = (
            "You investigate CLAIMED PATTERNS. Many people assert hidden patterns/conspiracies; your job "
            "is to adjudicate their claims fairly and rigorously — NOT to debunk reflexively and NOT to "
            "endorse. Work in this order for the case below.\n\n"
            "STEP 1 — WHO CLAIMS A PATTERN? From the findings, identify each distinct CLAIMED PATTERN "
            "(an alleged hidden connection, coordination, cover-up, or non-random cluster). For each, note "
            "WHO makes it (named journalist / official / anonymous social post / influencer / forum) and a "
            "one-word credibility read (high/medium/low/anonymous).\n"
            "STEP 2 — STEELMAN, THEN ATOMIZE. State the STRONGEST honest version of the claim in one line. "
            "Then break it into discrete, individually-checkable links (e.g. 'all six worked on program X'; "
            "'all died within N months'; 'all tied to person Y').\n"
            "STEP 3 — CHECK EACH LINK against the CONFIRMED LINKS, NON-CONNECTIONS, and LEDGERED FACTS "
            "provided. Verdict each atomic link: supported / debunked / unverified.\n"
            "STEP 4 — OVERALL VERDICT for the pattern, one of EXACTLY: 'supported', 'debunked', "
            "'unverified', or 'unresolved-notable'. Use 'unresolved-notable' when the claim is NOT proven "
            "but is still worth a reader's attention — e.g. it is only unproven because an investigation "
            "was halted, records are sealed, evidence was lost, or a knowable check was blocked. For "
            "'unresolved-notable' you MUST fill 'why_notable' AND 'why_unproven'.\n"
            "Also set 'connects_to_factual': if any part of a debunked/unverified claim nonetheless touches "
            "REAL confirmed connective tissue above, say what (this is how a dismissed claim can still add "
            "value); else ''.\n"
            "Flag in 'selection_bias' any pattern that is manufactured by cherry-picking (a seed case that "
            "does not generalize).\n\n"
            "HARD RULES: invent NOTHING. Adjudicate the CLAIM, never assert that a named living person is "
            "guilty of anything. A person may be named only if the findings already name them publicly. "
            "Every verdict must be justifiable from the material below. Prefer 'unverified' over guessing.\n\n"
            f"CASE: {subject}\n\n"
            f"CONFIRMED LINKS (Seeker's own verified connections):\n{conf_txt}\n\n"
            f"VERIFIED NON-CONNECTIONS (checked, none found):\n{non_txt}\n\n"
            f"LEDGERED FACTS:\n{facts_txt}\n\n"
            f"FINDINGS (where the claims live):\n{claim_blob}\n\n"
            'Return STRICT JSON: {"claimed_patterns": [{"pattern": "...", "claimants": [{"who": "...", '
            '"credibility": "high|medium|low|anonymous"}], "atomic_links": [{"link": "...", "verdict": '
            '"supported|debunked|unverified", "basis": "..."}], "verdict": "supported|debunked|unverified|'
            'unresolved-notable", "why_notable": "", "why_unproven": "", "connects_to_factual": ""}], '
            '"folded_count": 0, "selection_bias_flags": ["..."]}. '
            "'folded_count' = how many additional LOW-credibility fringe variants you saw but did not list "
            "individually (so the reader knows noise exists without drowning in it).")
        data = _reason_json(prompt)
        if not isinstance(data, dict):
            return _empty()

        out = []
        counts = {v: 0 for v in VERDICTS}
        for p in (data.get("claimed_patterns") or [])[:20]:
            if not isinstance(p, dict) or not p.get("pattern"):
                continue
            verdict = _norm_verdict(p.get("verdict"))
            counts[verdict] += 1
            claimants = []
            for c in (p.get("claimants") or [])[:6]:
                if isinstance(c, dict) and c.get("who"):
                    claimants.append({"who": str(c["who"]).strip(),
                                      "credibility": str(c.get("credibility", "")).strip().lower()})
            links = []
            for a in (p.get("atomic_links") or [])[:8]:
                if isinstance(a, dict) and a.get("link"):
                    links.append({"link": str(a["link"]).strip(),
                                  "verdict": _norm_verdict(a.get("verdict")),
                                  "basis": str(a.get("basis", "")).strip()})
            out.append({
                "pattern": str(p["pattern"]).strip(),
                "claimants": claimants,
                "atomic_links": links,
                "verdict": verdict,
                "why_notable": str(p.get("why_notable", "")).strip(),
                "why_unproven": str(p.get("why_unproven", "")).strip(),
                "connects_to_factual": str(p.get("connects_to_factual", "")).strip(),
            })
        # Rank so the reader sees signal first: unresolved-notable and supported before debunked, then
        # by how much cross-referenced structure the claim carries.
        order = {"unresolved-notable": 0, "supported": 1, "unverified": 2, "debunked": 3}
        out.sort(key=lambda p: (order.get(p["verdict"], 4),
                                -len(p["atomic_links"]), -bool(p["connects_to_factual"])))
        folded = int(data.get("folded_count", 0) or 0)
        bias = [str(x).strip() for x in (data.get("selection_bias_flags") or []) if str(x).strip()][:8]
        return {"claimed_patterns": out, "folded_count": folded,
                "selection_bias_flags": bias, "counts": counts}
    except Exception:
        return _empty()


def _empty() -> dict:
    return {"claimed_patterns": [], "folded_count": 0, "selection_bias_flags": [],
            "counts": {v: 0 for v in VERDICTS}}
