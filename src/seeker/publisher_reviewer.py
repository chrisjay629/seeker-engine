"""Publisher-Reviewer — the last gate before an investigation is published (task #37).

TWO OPEN LOOPS, ONE MODULE (Zara). Both read the same artifact — `runs/bias_lean_card.md`, the
MEASURED lean of each candidate writer produced by bias_probe.py:

  1. synthesis_model()  — ROUTING. The card measured which model distorts least; nothing ever read
     it, so Quill stayed hardcoded to gpt-4.1 while the card said gemini-2.5-flash was cleaner.
     The measurement existed and changed nothing. This closes that loop.
  2. review()           — THE GATE. An INDEPENDENT reviewer screens the finished prose for the
     failures the card measures (softening the honest verdict, stripping context that changes
     meaning) plus the publish-blockers: false balance, loaded framing, selective citation, and
     — the one that actually matters when writing about real dead people — accusing a named person.

WHY A DISTINCT GATE (Noor). Quill.critique() already exists, but Quill critiquing Quill is marking
its own homework, and it asks a different question anyway ("is this flat?" — an editorial-quality
question, not an honesty question). The reviewer is deliberately a DIFFERENT model from the writer:
if the writer softened, the model that softened it is the last one who will notice.

FAIL-OPEN, NEVER FAIL-SILENT (Vera). Any error returns a neutral "unreviewed" verdict rather than
blocking a run — but an "unreviewed" or "revise" verdict is surfaced in the dossier, never swallowed.
This gate advises; it does not silently rewrite or silently pass.

Ghost: the accusation check is a HARD flag, not a style note. Seeker investigates evidence and
theories and never asserts a named person's guilt.
"""
from __future__ import annotations

import os
import re

from . import config
from .memory.gap_detector import _cheap_json

_CARD_PATH = os.environ.get("SEEKER_BIAS_CARD", "runs/bias_lean_card.md")

# Fallback order when the card is missing/unparseable — the card is the authority, this is only a
# floor so routing never returns nothing.
_DEFAULT_WRITER = "openai/gpt-4.1"


def _card_rows(path: str = _CARD_PATH) -> list:
    """Parse the lean card's table -> [(model, lean_score)], lowest lean first. [] if unreadable.

    Row shape: | `openai/gpt-4.1` | 3 / 2 | 1 / 5 | +3 |
                 model              soft(on/off) strip(on/off)
    We score on the PROTOCOL-ON numbers (softening_on + stripping_on) because Seeker always runs
    with the neutrality protocol on — the 'off' column exists to show whether the protocol helps,
    not to describe how we actually run."""
    try:
        with open(path) as f:
            text = f.read()
    except Exception:
        return []
    rows = []
    for line in text.splitlines():
        m = re.match(r"\s*\|\s*`([^`]+)`\s*\|\s*(\d+)\s*/\s*\d+\s*\|\s*(\d+)\s*/\s*\d+\s*\|", line)
        if m:
            model, soft_on, strip_on = m.group(1), int(m.group(2)), int(m.group(3))
            rows.append((model, soft_on + strip_on))
    rows.sort(key=lambda r: r[1])
    return rows


def synthesis_model(default: str = _DEFAULT_WRITER) -> str:
    """ROUTING: the least-distorting capable writer, per the measured lean card.

    Closes the loop bias_probe.py was built for. Off-switch: SEEKER_BIAS_ROUTING=0 (or an explicit
    QUILL_MODEL env) keeps the caller's default, so a human override always wins."""
    if os.environ.get("SEEKER_BIAS_ROUTING", "1") == "0" or os.environ.get("QUILL_MODEL"):
        return default
    rows = _card_rows()
    return rows[0][0] if rows else default


def reviewer_model(writer_model: str) -> str:
    """INDEPENDENCE: a reviewer that is NOT the writer (Noor — no marking your own homework).
    Prefers the next-cleanest model on the card; falls back to the reasoning tier, and only ever
    returns the writer itself if there is genuinely no alternative."""
    for model, _lean in _card_rows():
        if model != writer_model:
            return model
    alt = getattr(config, "REASONING_MODEL", "") or ""
    return alt if alt and alt != writer_model else writer_model


def review(prose: str, *, question: str = "", roster: list | None = None,
           writer_model: str = "") -> dict:
    """THE GATE. Screen finished prose before publish. Returns:
        {"verdict": "publish"|"revise"|"unreviewed",
         "flags": [{"kind","detail"}], "blocking": [..], "reviewer_model", "writer_model"}

    'revise' means a human (or Quill's revision pass) should act before this goes out. Fail-open to
    'unreviewed' — visible, never a silent pass."""
    out = {"verdict": "unreviewed", "flags": [], "blocking": [],
           "reviewer_model": "", "writer_model": writer_model}
    text = (prose or "").strip()
    if not text:
        return out
    writer = writer_model or synthesis_model()
    rmodel = reviewer_model(writer)
    out["writer_model"], out["reviewer_model"] = writer, rmodel
    names = ", ".join(str(n) for n in (roster or [])[:15])
    try:
        data = _cheap_json(
            "You are the PUBLISHER-REVIEWER for an investigation engine — the last independent gate "
            "before a piece about REAL PEOPLE is published. You did not write this piece. Your job is "
            "honesty, not style (a separate editor already judged whether it reads well).\n\n"
            "Flag ONLY what you can point at in the text. For each flag give kind + the specific "
            "sentence or phrase. Check, in order:\n"
            "1. ACCUSATION (BLOCKING): does it assert or imply a NAMED person committed a crime or "
            "wrongdoing? Reporting that officials ruled something, or that a person was charged, is "
            "FINE — asserting guilt, or nudging the reader toward a named suspect, is NOT.\n"
            "2. SOFTENING: is a documented, well-supported finding cushioned, hedged, or buried so it "
            "lands softer than the evidence warrants?\n"
            "3. STRIPPING: is context dropped whose absence changes the meaning of a claim?\n"
            "4. FALSE BALANCE: are a well-supported finding and a fringe/unverified claim presented "
            "as comparably credible?\n"
            "5. LOADED FRAMING: language that presumes a conclusion the evidence does not carry "
            "(e.g. implying a pattern or foul play the findings do not establish).\n"
            "6. SELECTIVE CITATION: does it lean on the sources that fit a story while ignoring "
            "contrary evidence it clearly had?\n"
            "7. TIER FIDELITY: are unverified/contested claims presented as settled fact?\n\n"
            "Be strict but concrete: no flag without a quote. An honest, blunt verdict is NOT a "
            "problem — do not ask for hedging or 'balance' the evidence doesn't support.\n\n"
            f"CASE QUESTION: {question or '(not provided)'}\n"
            + (f"PEOPLE IN THIS CASE: {names}\n" if names else "")
            + f"\nPIECE:\n{text[:9000]}\n\n"
            'Return STRICT JSON: {"flags": [{"kind": "accusation|softening|stripping|false_balance|'
            'loaded_framing|selective_citation|tier_fidelity", "detail": "the quote + what is wrong"}], '
            '"verdict": "publish" or "revise"}', model=rmodel)
        if not isinstance(data, dict):
            return out
        flags = []
        for f in (data.get("flags") or [])[:12]:
            if isinstance(f, dict) and str(f.get("detail", "")).strip():
                flags.append({"kind": str(f.get("kind", "")).strip() or "unspecified",
                              "detail": str(f.get("detail", "")).strip()[:400]})
        out["flags"] = flags
        out["blocking"] = [f for f in flags if f["kind"] == "accusation"]
        verdict = str(data.get("verdict", "")).strip().lower()
        # an accusation flag forces revise regardless of the model's own verdict (Ghost: hard rule)
        out["verdict"] = "revise" if (out["blocking"] or verdict == "revise") else "publish"
        return out
    except Exception:
        return out
