"""The public failure log — the failure wall (blueprint, Phase 1).

Every investigation cycle that breaks or gets something wrong is published with
its full reasoning trail — front and center, not buried. Failures become
teaching documents. This operationalizes the verification spine in public:
instead of hiding a flaw, Seeker publishes the investigation into why.

Format per entry: question asked, path followed, where it failed, reasoning
trail, correction, current status.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import REPO_ROOT

JSONL_PATH = REPO_ROOT / "runs" / "failure_log.jsonl"
WALL_PATH = REPO_ROOT / "FAILURE_WALL.md"


def log_failure(*, question: str, path: str, where_failed: str,
                reasoning_trail: list, correction: str,
                status: str = "recovered", branch_id: str = "main") -> dict:
    entry = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "path": path,
        "where_failed": where_failed,
        "reasoning_trail": reasoning_trail,
        "correction": correction,
        "status": status,
        "branch_id": branch_id,
    }
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSONL_PATH.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    _append_wall(entry)
    return entry


def _append_wall(e: dict) -> None:
    if not WALL_PATH.exists():
        WALL_PATH.write_text(
            "# Seeker Failure Wall\n\n"
            "Every investigation that broke or got something wrong, published in "
            "full. The inverse of a marketing page: here is where Seeker failed, "
            "how it caught it, and how it corrected. Failures are teaching "
            "documents.\n\n---\n\n")
    lines = [
        f"## {e['logged_at']} — {e['status'].upper()}",
        "",
        f"**Question:** {e['question']}",
        f"**Path followed:** {e['path']}",
        f"**Where it failed:** {e['where_failed']}",
        "",
        "**Reasoning trail:**",
    ]
    for i, step in enumerate(e["reasoning_trail"], 1):
        lines.append(f"{i}. {step}")
    lines += ["", f"**Correction:** {e['correction']}", "", "---", ""]
    with WALL_PATH.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
