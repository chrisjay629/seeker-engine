"""Multi-source parallel sweep.

Fires ONE question to many independent voices and returns each answer as its
own SourceResponse. Never merges them — disagreement is preserved downstream
(Gap Detector, brief 03). No self-grading here: this module only collects.
"""
from __future__ import annotations

import concurrent.futures as cf
from typing import Callable

import requests

from .. import config
from ..models import SourceResponse

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"


def _chat(url: str, key: str, model: str, question: str, provider: str = "default") -> str:
    from ..neutrality import frame
    from .. import ratelimit
    resp = ratelimit.post(
        provider, url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": frame(question)}]},
        timeout=config.REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _openrouter_source(model: str, question: str, question_id: str,
                       branch_id: str, bucket: str) -> SourceResponse:
    try:
        text = _chat(_OPENROUTER_URL, config.OPENROUTER_API_KEY, model, question, "openrouter")
        return SourceResponse(question_id, "llm", model, text,
                              branch_id=branch_id, rate_limit_bucket=bucket)
    except Exception as e:  # a broken source is data, not a crash
        return SourceResponse(question_id, "llm", model, "", error=repr(e),
                              branch_id=branch_id, rate_limit_bucket=bucket)


def _groq_source(question: str, question_id: str,
                 branch_id: str, bucket: str) -> SourceResponse:
    label = f"groq/{config.GROQ_RECON_MODEL}"
    try:
        text = _chat(_GROQ_URL, config.GROQ_API_KEY, config.GROQ_RECON_MODEL, question, "groq")
        return SourceResponse(question_id, "llm", label, text,
                              branch_id=branch_id, rate_limit_bucket=bucket)
    except Exception as e:
        return SourceResponse(question_id, "llm", label, "", error=repr(e),
                              branch_id=branch_id, rate_limit_bucket=bucket)


def _perplexity_source(question: str, question_id: str,
                       branch_id: str, bucket: str) -> SourceResponse:
    """The web-grounded voice — returns an answer plus live citations."""
    from ..models import Citation
    from ..neutrality import frame
    from .. import ratelimit
    label = f"perplexity/{config.PERPLEXITY_RECON_MODEL}"
    try:
        resp = ratelimit.post(
            "perplexity", _PERPLEXITY_URL,
            headers={"Authorization": f"Bearer {config.PERPLEXITY_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.PERPLEXITY_RECON_MODEL,
                  "messages": [{"role": "user", "content": frame(question)}]},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        cites = []
        for sr in data.get("search_results", []) or []:
            cites.append(Citation(url=sr.get("url", ""), title=sr.get("title", ""),
                                  source_type="perplexity"))
        if not cites:  # older shape: flat "citations" url list
            for u in data.get("citations", []) or []:
                cites.append(Citation(url=u, source_type="perplexity"))
        return SourceResponse(question_id, "perplexity", label, text, citations=cites,
                              branch_id=branch_id, rate_limit_bucket=bucket)
    except Exception as e:
        return SourceResponse(question_id, "perplexity", label, "", error=repr(e),
                              branch_id=branch_id, rate_limit_bucket=bucket)


def sweep(question: str, question_id: str, *,
          branch_id: str = "main", rate_limit_bucket: str = "main",
          max_workers: int = 8) -> list:
    """Fire the question to every source in parallel. Returns a list of
    SourceResponse — one per voice, kept separate. Failures come back as
    SourceResponse.error (absence of a voice is itself data)."""
    tasks: list[Callable[[], SourceResponse]] = []
    for model in config.OPENROUTER_RECON_MODELS:
        model = model.strip()
        if model:
            tasks.append(lambda m=model: _openrouter_source(
                m, question, question_id, branch_id, rate_limit_bucket))
    tasks.append(lambda: _groq_source(question, question_id, branch_id, rate_limit_bucket))
    tasks.append(lambda: _perplexity_source(question, question_id, branch_id, rate_limit_bucket))

    results: list[SourceResponse] = []
    with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for r in pool.map(lambda t: t(), tasks):
            results.append(r)
    return results
