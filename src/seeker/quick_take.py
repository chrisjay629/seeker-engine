"""Quick-take mode — an instant, honesty-flavored answer before the deep dive.

Perplexity's one real edge in the head-to-head was SPEED (seconds vs minutes). This
neutralizes it without abandoning what makes Seeker different: a fast pass that STILL
preserves disagreement (unlike a single confident paragraph), delivered first — then the
full compounding investigation runs for the deep, per-claim-labeled map.

Built on the existing Recon Pass primitive (`recon.sources.sweep`) — the fast multi-source
parallel sweep — so this is a new user-facing layer, not a new organ. Spine intact: it
flags where independent sources disagree instead of smoothing them into false consensus.
"""
from __future__ import annotations

import concurrent.futures as cf

import requests

from . import config
from .recon import sources


def _fast_sources(question: str, branch_id: str, bucket: str) -> list:
    """Only the two FASTEST independent voices — Groq (fast) + Perplexity (grounded).
    Two sources is enough to flag a disagreement while staying near one-shot speed."""
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(sources._groq_source, question, "quick", branch_id, bucket),
                ex.submit(sources._perplexity_source, question, "quick", branch_id, bucket)]
        return [f.result() for f in futs]


def _fast_text(prompt: str, max_tokens: int = 420) -> str:
    """One cheap, fast completion (the extractor-tier model) for prose."""
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.EXTRACTOR_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": max_tokens},
            timeout=60)
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        return f"(quick take unavailable — {repr(e)[:80]})"


def quick_take(question: str, *, branch_id: str = "main",
               rate_limit_bucket: str = "main", fast: bool = True) -> dict:
    """Fast, honest first answer: query independent sources in parallel, then synthesize
    a short take that STATES agreement and FLAGS disagreement. Returns
    {"answer": str, "n_sources": int}.

    fast=True (default): only the 2 fastest voices (Groq + Perplexity) — ~10-15s, near
    one-shot speed, still flags disagreement. fast=False: the full multi-source sweep — a
    'deep quick-take', slower (~a minute) but more cross-checked."""
    responses = (_fast_sources(question, branch_id, rate_limit_bucket) if fast
                 else sources.sweep(question, "quick", branch_id=branch_id,
                                    rate_limit_bucket=rate_limit_bucket))
    ok = [r for r in responses if getattr(r, "ok", False)
          and getattr(r, "raw_text", "").strip()]
    if not ok:
        return {"answer": "(quick take unavailable — no sources responded)", "n_sources": 0}
    if len(ok) < 2:
        # Only one voice answered — be honest that there was NO cross-check (Vera):
        # a single-source quick-take must not imply it compared independent sources.
        one = _fast_text(
            "Summarize this single source's answer in 3-4 sentences. Do NOT imply "
            "multiple sources or consensus.\n\nQUESTION: " + question +
            "\n\nSOURCE:\n" + ok[0].raw_text[:1600])
        return {"answer": one + "\n\n(Only ONE source responded — this quick-take could "
                "NOT cross-check for disagreement. The deep investigation will.)",
                "n_sources": 1}
    blob = "\n\n".join(f"[{getattr(r, 'source_label', 'src')}]\n{r.raw_text[:1400]}"
                       for r in ok)
    prompt = (
        "Several INDEPENDENT sources answered the question below. Write a SHORT quick-take "
        "(4-6 sentences). Where the sources AGREE, state it plainly. Where they DISAGREE or "
        "are uncertain, FLAG it explicitly ('sources disagree on ...') — do NOT smooth "
        "disagreement into false consensus. No fabricated certainty. End with exactly this "
        "line: 'Quick take only — the deep investigation will verify and confidence-label "
        "each claim.'\n\n"
        f"QUESTION: {question}\n\nSOURCES:\n{blob}")
    return {"answer": _fast_text(prompt), "n_sources": len(ok)}
