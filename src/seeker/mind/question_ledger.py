"""Question Ledger (owned by the Mind, brief 05).

Logs every question and its outcome, never repeats, is the public proof-of-work
trail. Phase 1: append-only JSONL on disk + exact/normalized dedupe. Circling
detection by embedding similarity is a later upgrade (noted).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import REPO_ROOT

LEDGER_PATH = REPO_ROOT / "runs" / "question_ledger.jsonl"


def _norm(text: str) -> str:
    return " ".join(text.lower().split()).rstrip("?. ")


def _load() -> list:
    if not LEDGER_PATH.exists():
        return []
    out = []
    for line in LEDGER_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def seen(text: str, branch_id: str = "main") -> bool:
    n = _norm(text)
    return any(_norm(e["text"]) == n and e.get("branch_id", "main") == branch_id
               for e in _load())


def log(text: str, *, branch_id: str = "main", cycle_n: int = 0,
        scores: dict | None = None, outcome: str = "proposed") -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {"text": text, "branch_id": branch_id, "cycle_n": cycle_n,
             "scores": scores or {}, "outcome": outcome}
    with LEDGER_PATH.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def all_entries(branch_id: str | None = None) -> list:
    entries = _load()
    if branch_id:
        entries = [e for e in entries if e.get("branch_id") == branch_id]
    return entries
