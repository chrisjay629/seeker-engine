"""Claim Ledger (Chris's idea, 2026) — rule on EACH claim, not just the case.

For a contested/conspiracy topic, a single verdict throws away the interesting part: some sub-claims
are true, some are debunked, some link to something real, some are pure hearsay. This breaks a case
into its specific claims and gives EACH one a reader-friendly verdict, grounded only in the map's
findings. Makes the final report both more honest and more engaging.

Verdict vocabulary: verified / debunked / real-link / hearsay / unproven / contested.

Spine (Vera + Ghost): verdicts come from the evidence on the map, never from vibes; where a claim
implicates a NAMED person, the THEORY is labeled speculation and no person is accused of anything.
Grounded-only; no outside knowledge; honest 'unproven' when evidence is genuinely absent (Noor).
"""
from __future__ import annotations

from .memory.memory_map import MemoryMap
from .memory.gap_detector import _reason_json
from . import synthesis as _synthesis

_VERDICTS = ("verified", "debunked", "real-link", "hearsay", "unproven", "contested")
_LEANS = ("toward", "away", "balanced")
_MAGS = ("slight", "moderate", "strong")


def claim_ledger(question: str, *, branch_id: str = "main", mm: MemoryMap | None = None,
                 top_k: int | None = None, max_claims: int = 14) -> dict:
    """Return {"claims": [{"claim","verdict","why"}], "n": int}. Each notable claim in the case
    gets one verdict from the vocabulary, plus a one-line reason, built only from the findings."""
    mm = mm or MemoryMap()
    buckets = _synthesis.gather_findings(question, branch_id=branch_id, top_k=top_k, mm=mm)
    rows = []
    for label in ("well-supported", "contested", "unverified", "disproven"):
        for r in buckets.get(label, []):
            rows.append(f"[{label}] {r['claim']}")
    if not rows:
        return {"claims": [], "n": 0, "note": "no findings on the map for this question yet"}
    blob = "\n".join(rows)   # every finding: the ledger decides what is VERIFIED, on 14% before
    prompt = (
        "You are compiling a CLAIM LEDGER for a contested/conspiracy topic. Below are atomic findings "
        "with the evidence-tier they were assigned. Group them into the distinct CLAIMS a reader would "
        "recognize, and give EACH claim ONE verdict from this exact set:\n"
        "- verified   = documented, genuinely true\n"
        "- debunked   = shown false / no truth\n"
        "- real-link  = connects to something genuinely real, even though the sinister interpretation is unproven\n"
        "- hearsay    = a single-source or uncorroborated account\n"
        "- unproven   = interesting but no evidence either way\n"
        "- contested  = credible sources genuinely disagree\n\n"
        "NAME FIDELITY: when a claim names a specific person, use the spelling from the most "
        "authoritative/primary finding; never adopt a variant spelling from a lower-quality source. "
        "Hard rules: base every verdict ONLY on the findings below (no outside knowledge). If a claim "
        "or theory implicates a NAMED person in wrongdoing, label the THEORY 'unproven' or 'hearsay' "
        "and do NOT state or imply the person did anything. Prefer 'unproven' over 'debunked' when "
        "evidence is merely absent. Keep 'why' to one plain sentence.\n\n"
        "ALSO give each UNSETTLED claim (unproven/contested/hearsay/real-link) a directional LEAN — "
        "which way the GATHERED EVIDENCE currently tilts. Three hard rules for the lean:\n"
        "1. It describes OUR evidence, never reality. 'lean:away' means 'more of what we found points "
        "away' — NEVER a probability that the claim is false.\n"
        "2. Weight by QUALITY not COUNT: many uncorroborated/single-source findings saying the same "
        "thing count as little; corroborated or primary-source findings count heavily.\n"
        "3. Absence-of-evidence caveat: if the claim is a cover-up/suppression theory (missing "
        "evidence is EXPECTED), do NOT lean hard 'away' merely because evidence is absent — use "
        "'balanced' and say so in 'why'.\n"
        "For settled verdicts (verified/debunked) use lean 'toward'/'away' with magnitude 'strong'.\n\n"
        f"TOPIC: {question}\n\nFINDINGS:\n{blob}\n\n"
        f"Return STRICT JSON: {{\"claims\": [{{\"claim\": \"...\", \"verdict\": \"one of "
        f"{'/'.join(_VERDICTS)}\", \"lean\": \"one of toward/away/balanced\", "
        f"\"magnitude\": \"one of slight/moderate/strong\", \"why\": \"one sentence\"}}]}} "
        f"— up to {max_claims} claims.")
    data = _reason_json(prompt)
    out = []
    for c in (data.get("claims", []) if isinstance(data, dict) else []):
        if not isinstance(c, dict):
            continue
        v = str(c.get("verdict", "")).strip().lower()
        if v not in _VERDICTS:
            v = "unproven"
        lean = str(c.get("lean", "")).strip().lower()
        if lean not in _LEANS:
            lean = "balanced"
        mag = str(c.get("magnitude", "")).strip().lower()
        if mag not in _MAGS:
            mag = "slight"
        # settled verdicts are directionally strong by definition; keep the model honest
        if v == "verified":
            lean, mag = "toward", "strong"
        elif v == "debunked":
            lean, mag = "away", "strong"
        claim = str(c.get("claim", "")).strip()
        if claim:
            out.append({"claim": claim, "verdict": v, "lean": lean, "magnitude": mag,
                        "why": str(c.get("why", "")).strip()})
    return {"claims": out[:max_claims], "n": len(out[:max_claims])}
