"""Recency filter — wired to the Truth Anchor's freshness field.

Fast-moving topics (current AI, self-sustainability) get better results from
recent sources; a 10-year-old transcript is bloat. Freshness maps to a published-
date window applied at Exa SEARCH time (`startPublishedDate`), so old sources are
never fetched.

HEURISTIC, not truth (Vera/Elara): old != wrong. The window is a user-confirmed
default, overridable per investigation. Canonical-but-old sources should be
surfaced, not silently dropped (Noor) — a caller can pass recency_years=None to
widen to all time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

# Truth Anchor freshness -> recency window in years (None = no date filter)
FRESHNESS_YEARS = {
    "rapid": 2, "rapidly": 2, "changes rapidly": 2,
    "annual": 5, "annually": 5, "changes annually": 5,
    "stable": None,
}


def years_for_freshness(freshness: Optional[str]) -> Optional[int]:
    """Map a Truth Anchor freshness label to a recency window in years."""
    if not freshness:
        return None
    return FRESHNESS_YEARS.get(freshness.strip().lower())


def start_date(recency_years: Optional[int]) -> Optional[str]:
    """ISO `startPublishedDate` for Exa, or None for no filter (all time)."""
    if not recency_years or recency_years <= 0:
        return None
    dt = datetime.now(timezone.utc) - timedelta(days=365 * recency_years)
    return dt.strftime("%Y-%m-%dT00:00:00.000Z")
