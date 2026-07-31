"""KB-first lookup (backlog A1) — reuse the graded map before researching.

Before Seeker spends a whole research loop on a sub-question, it checks its OWN graded memory:
is there already a well-supported, cross-verified, still-fresh answer? If so, reuse it and skip
the loop. Seeker gets faster AND smarter as its knowledge base grows — the compounding win.
Token savings are the side-effect, never the pitch (token guardrail).

Spine (Vera): reuse is a READ of externally-graded evidence, not self-grading. It fires only for
a top-tier ("Accepted"), genuinely cross-corroborated, semantically-matching, fresh, and cited
node — a contested / speculative / single-source / self-written node never qualifies. Freshness
(Noor): a stale well-supported node is re-verified, not blindly reused; a node later flipped to
Contested/Disproven auto-disqualifies via the tier gate. Provenance (Luna): the caller logs the
reuse so an instant answer is always visibly a reuse, never a silent one.
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from .. import config
from ..memory.memory_map import MemoryMap

# Cosine is only a cheap PRE-FILTER here, not the decision. Matching a QUESTION to a stored
# ANSWER is not the same problem as dedup (statement-vs-statement): a question and the statement
# that answers it are phrased differently, so they sit a bit further apart in embedding space.
# The dedup floor (0.60) is measured for statement-vs-statement and is too strict here — a close
# paraphrase question lands ~0.56. So we pre-filter loosely, then let a cheap LLM judge make the
# actual reuse call (verification from outside the geometry — spine-aligned).
_SIM_PREFILTER = 0.50
_TOP_TIER = "Accepted"   # "widely corroborated across independent sources" — the well-supported tier
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _answers_question(question: str, claim: str) -> bool:
    """Cheap Groq judge: does this stored finding DIRECTLY answer the question? Fails CLOSED —
    on any error, return False so we research instead of reusing (a wrong reuse is a silent
    correctness hole; a redundant research loop is merely slower). This is the real reuse gate;
    cosine only narrows to a plausible candidate."""
    prompt = (f"QUESTION: {question}\n\nCANDIDATE ANSWER (a stored research finding):\n{claim}\n\n"
              "Does the candidate DIRECTLY and substantively answer the question (not merely "
              "share the topic)? Answer with only one word: yes or no.")
    try:
        r = requests.post(
            _GROQ_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": config.GROQ_RECON_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0, "max_tokens": 4},
            timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip().lower().startswith("y")
    except Exception:
        return False  # fail CLOSED — when unsure, research rather than reuse (Vera/Noor)


def _age_days(created_at: str | None) -> float | None:
    """Age of a node in days from its ISO `created_at`, or None if unparseable."""
    if not created_at:
        return None
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except Exception:
        return None


def kb_lookup(question: str, *, branch_id: str = "main", mm: MemoryMap | None = None,
              sim_floor: float = _SIM_PREFILTER, min_corroboration: int = 2,
              max_age_days: float | None = None) -> dict | None:
    """Return a reuse-hit for `question` if the map already holds a qualifying answer, else None.

    Vector-only query so the score is a real COSINE we can threshold (hybrid mixes in BM25, which
    isn't a similarity we can gate on). Reads the authoritative metadata by id (strongly consistent)
    so a just-demoted tier or a fresh corroboration bump is reflected immediately."""
    mm = mm or MemoryMap()
    hits = mm.query(question, branch_id=branch_id, top_k=5, node_kind="finding", hybrid=False)
    if not hits:
        return None
    # Evaluate candidates BEST-FIRST — never assume the top slot is the best match (the vector
    # query does not always return score-sorted). Return the first candidate that clears every
    # gate; a distractor that fails the judge must not shadow a real answer ranked below it.
    cands = sorted((h for h in hits if h.get("score", 0.0) >= sim_floor),
                   key=lambda h: h.get("score", 0.0), reverse=True)
    for best in cands:
        fid = best.get("id")
        if not fid:
            continue
        meta = mm.get_metas([fid], branch_id=branch_id).get(fid, {})
        tier = meta.get("confidence_tier") or best.get("confidence_tier", "Speculative")
        if tier != _TOP_TIER:                          # only the top, well-supported tier (Vera)
            continue
        try:
            corro = int(meta.get("corroboration_count", 1) or 1)
        except Exception:
            corro = 1
        if corro < min_corroboration:                  # must be genuinely cross-source
            continue
        urls = [u for u in (meta.get("urls") or []) if u and u != "_"]
        if not urls:                                   # must be auditable (Ghost)
            continue
        age = _age_days(meta.get("created_at"))
        if max_age_days is not None and age is not None and age > max_age_days:
            continue                                   # stale — re-verify, don't reuse (Noor)
        # final gate: a cheap judge confirms the finding actually ANSWERS the question, not just
        # shares its topic — the real reuse decision, verified from outside the geometry (Vera).
        if not _answers_question(question, best.get("text", "")):
            continue
        return {"hit": True, "claim": best.get("text", ""), "finding_id": fid,
                "tier": tier, "corroboration": corro,
                "age_days": round(age, 1) if age is not None else None, "urls": urls}
    return None
