"""Research Extractor (owned by brief 01).

Evaluates fetched content (a transcript or a page) against the investigation
question and returns relevant atomic claims + a citation. Comprehension-LITE:
a cheap model, NOT the Mind. It extracts; it does not grade its own work and
it does not decide the investigation is done (verification spine).
"""
from __future__ import annotations

import json
from typing import Optional

import requests

from .. import config
from ..models import Citation, Finding

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_PROMPT = """You are a research extractor. Given an investigation QUESTION and \
some SOURCE CONTENT, pull out only the atomic factual claims in the content that \
are relevant to the question.

Rules:
- Each claim must be ONE self-contained factual assertion.
- Only include claims actually supported by the content. Do not add outside knowledge.
- If the content is irrelevant to the question, return an empty list.
- Do NOT rate your own performance or judge quality. Just extract.
- Keep each claim's interpretive context WITH it: figures carry their denominators / per-capita
  basis / timeframe / dataset and any confounder the content states — never strip a statistic to
  a bare number. Exclude the source's moral editorializing; keep its factual assertions.

Return STRICT JSON: {"relevant": true/false, "claims": ["...", "..."]}

QUESTION:
{question}

SOURCE CONTENT (may be truncated):
{content}
"""


def extract(question: str, content: str, citation: Citation, *,
            branch_id: str = "main", max_chars: int = 8000) -> list:
    """Return a list[Finding] of relevant atomic claims from `content`.
    Empty list if irrelevant or on failure (absence is data, not a crash)."""
    content = (content or "").strip()
    if not content:
        return []
    from .. import watchdog
    watchdog.beat("extracting")   # every extraction is retrieval progress — resets the stall clock
    # Persist the ORIGINAL text this node is extracted from, so the finding can be
    # traced back / re-scanned / restored (Proposal 1 prerequisite). Fail-safe:
    # a store outage never blocks extraction. One hook covers YouTube + web.
    from ..memory import source_store
    source_store.save(citation.url, content, title=citation.title,
                      source_type=citation.source_type, branch_id=branch_id)
    prompt = _PROMPT.replace("{question}", question).replace(
        "{content}", content[:max_chars])
    try:
        from .. import ratelimit
        resp = ratelimit.post(
            "openrouter", _OPENROUTER_URL,
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.EXTRACTOR_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "response_format": {"type": "json_object"}},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(raw)
    except Exception:
        return []

    if not data.get("relevant") or not data.get("claims"):
        return []
    findings = []
    for claim in data["claims"]:
        if isinstance(claim, str) and claim.strip():
            findings.append(Finding(claim=claim.strip(),
                                    citations=[citation],
                                    confidence_tier="Speculative",
                                    branch_id=branch_id))
    return findings
