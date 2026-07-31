"""Neutrality protocol — the bias-resistance layer (brief 23).

A strict evidence-first framing prepended to every SOURCE-FACING and SYNTHESIS LLM call, to
REDUCE (never eliminate) the bias each model (GPT/Grok/Claude/Perplexity) injects. A prompt
nudges a model; it cannot reach into its weights and delete the lean, and "be unbiased" can make
a model SOUND neutral while still leaning — so this is bias-REDUCTION, not elimination. The real
de-biasing is architectural: primary data, independent sources, external verification, and
confidence labels set by evidence. This is the top layer that helps at the edges.

Design principle — the doctor's diagnosis (Chris): separate the FINDING from the FRAMING. Never
soften, hedge, or dress up the finding — "this is what the evidence shows, this is what it is."
Tone may be humane; substance is unsoftened. No fluff, no slop, no sugarcoat.

Two non-negotiables (Elara + Vera): (1) "just the facts" means facts WITH their context — figures
carry their denominators / PER-CAPITA basis / base rates / confounders, never a bare number
(a stripped statistic is a misleading half-truth, its own bias); (2) never claim "unbiased."
"""
from __future__ import annotations

PROTOCOL = (
    "NEUTRALITY PROTOCOL (follow strictly):\n"
    "- Answer only from verifiable evidence; cite specifics.\n"
    "- Report figures WITH their denominators, per-capita/rate basis, base rates, timeframe, and "
    "dataset, plus known confounders — never a bare statistic stripped of what is needed to "
    "interpret it honestly.\n"
    "- Distinguish clearly what is well-established from what is disputed or uncertain; state "
    "uncertainty plainly.\n"
    "- Exclude moral judgment, advocacy, and editorializing — describe what the evidence shows, "
    "not how one should feel about it.\n"
    "- Do NOT soften, omit, hedge, or amplify a finding because it is politically or emotionally "
    "sensitive; treat sensitive and mundane facts identically.\n"
    "- Where the evidence is genuinely mixed, present each side's strongest evidence — "
    "manufacture neither false balance nor false consensus.\n"
    "- If the question's common framing is itself misleading (e.g. a comparison that ignores base "
    "rates or per-capita), say so and give the sounder framing.\n"
)

# A short emphasis appended on charged topics — the "deliver the diagnosis straight" reminder.
_SENSITIVE_EMPHASIS = (
    "This is a sensitive topic: deliver the finding straight and unsoftened, exactly as the "
    "evidence shows it. Do not add reassurance, disclaimers of feeling, or moral cushioning.\n"
)

# Cheap keyword gate — flags topics where models most often hedge. Not exhaustive; used only to
# ADD emphasis, never to change what evidence is gathered.
_SENSITIVE_KEYS = (
    "race", "racial", "ethnic", "gender", "sex ", "political", "politics", "election", "vote",
    "immigration", "immigrant", "religion", "religious", "abortion", "vaccine", "climate",
    "police", "crime", "shooting", "gun ", "inequality", "discrimination", "iq ", "wealth gap",
)


def sensitive_topic(question: str) -> bool:
    """True if the question touches a topic where models commonly hedge (cheap keyword gate)."""
    q = (question or "").lower()
    return any(k in q for k in _SENSITIVE_KEYS)


def protocol_block(question: str = "") -> str:
    """The protocol text for embedding inside an extraction/synthesis prompt. Adds the
    deliver-it-straight emphasis when the topic is sensitive."""
    block = PROTOCOL
    if question and sensitive_topic(question):
        block = block + _SENSITIVE_EMPHASIS
    return block


def frame(question: str) -> str:
    """Prepend the protocol to a question sent to a source voice (GPT/Groq/Perplexity)."""
    return protocol_block(question) + "\nQUESTION:\n" + (question or "")
