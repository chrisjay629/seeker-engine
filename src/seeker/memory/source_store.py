"""Raw source store (Phase 1.5 prerequisite) — persist the ORIGINAL text a
finding was extracted from, so a node can be traced back, re-scanned, or restored.

Nodes on the Memory Map store only the extracted claim + the source URL — never
the original transcript/article text (see memory_map.upsert_finding). That makes
the "link back to the original, re-scan, restore" requirement of conditional
extraction (Proposal 1) impossible, and makes any compression irreversible. A URL
alone is fragile: YouTube transcripts and pages disappear. So we persist the raw
text at ingest, keyed by (url, branch_id), in the SAME Supabase Postgres the
LangGraph checkpointer already uses — no new infra.

Spine: this is a sensor log, not ground truth. It stores what a source SAID, with
a timestamp; it never judges it. Fail-safe by design — if the store is down, an
extraction still succeeds (you just lose reversibility for that source, logged),
because absence of storage must never crash a hunt.
"""
from __future__ import annotations

import os
import threading

from .. import config

_TABLE = "seeker_raw_sources"
_lock = threading.Lock()
_conn = None
_ready = False

# Opt out for offline/unit tests without a DB (default: on).
ENABLED = os.environ.get("SEEKER_RAW_STORE", "1") not in ("0", "false", "False")


def _connect():
    """Lazily open (and cache) a psycopg connection to Supabase; ensure the
    table exists once. Returns None on any failure (caller degrades gracefully)."""
    global _conn, _ready
    if not ENABLED:
        return None
    with _lock:
        try:
            if _conn is None or _conn.closed:
                import psycopg
                _conn = psycopg.connect(config.require("SUPABASE_DB_URL"),
                                        autocommit=True)
                _ready = False
            if not _ready:
                _conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                    "url TEXT NOT NULL, branch_id TEXT NOT NULL DEFAULT 'main', "
                    "title TEXT, source_type TEXT, raw_text TEXT, "
                    "char_len INT, created_at TIMESTAMPTZ DEFAULT now(), "
                    "PRIMARY KEY (url, branch_id))")
                _ready = True
            return _conn
        except Exception:
            _conn = None
            return None


def ensure_table() -> bool:
    """Create the table if needed. True on success. Safe to call repeatedly."""
    return _connect() is not None


def save(url: str, raw_text: str, *, title: str = "", source_type: str = "web",
         branch_id: str = "main") -> bool:
    """Persist (or refresh) the raw text for a source. Idempotent on (url,
    branch_id). Fail-safe: returns False and never raises, so extraction proceeds
    even if the store is unavailable."""
    if not url or not raw_text:
        return False
    conn = _connect()
    if conn is None:
        return False
    try:
        with _lock:
            conn.execute(
                f"INSERT INTO {_TABLE} "
                "(url, branch_id, title, source_type, raw_text, char_len) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (url, branch_id) DO UPDATE SET "
                "raw_text = EXCLUDED.raw_text, char_len = EXCLUDED.char_len, "
                "title = EXCLUDED.title, source_type = EXCLUDED.source_type",
                (url, branch_id, title or "", source_type or "web",
                 raw_text, len(raw_text)))
        return True
    except Exception:
        return False


def get(url: str, *, branch_id: str = "main") -> dict | None:
    """Fetch the stored raw source for a URL, or None. This is the link-back a
    node follows to re-scan or restore its original text."""
    if not url:
        return None
    conn = _connect()
    if conn is None:
        return None
    try:
        with _lock:
            row = conn.execute(
                f"SELECT url, branch_id, title, source_type, raw_text, char_len, "
                f"created_at FROM {_TABLE} WHERE url = %s AND branch_id = %s",
                (url, branch_id)).fetchone()
        if not row:
            return None
        cols = ("url", "branch_id", "title", "source_type", "raw_text",
                "char_len", "created_at")
        return dict(zip(cols, row))
    except Exception:
        return None
