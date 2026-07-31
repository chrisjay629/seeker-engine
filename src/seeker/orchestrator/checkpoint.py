"""Supabase Postgres checkpointer for LangGraph (brief 02).

LangGraph's PostgresSaver.setup() creates its checkpoint tables via idempotent
migrations (it tracks a migration version and only applies new steps — it does
NOT wipe data). We still guard it behind an explicit call so nobody wires a
destructive schema.sql by mistake. Connection uses the Supabase Session pooler
(SUPABASE_DB_URL), which supports the prepared statements psycopg uses.
"""
from __future__ import annotations

from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver

from .. import config


@contextmanager
def checkpointer():
    """Yield a live PostgresSaver bound to Supabase. Use as a context manager."""
    url = config.require("SUPABASE_DB_URL")
    with PostgresSaver.from_conn_string(url) as cp:
        yield cp


def setup_once() -> None:
    """Create/upgrade the LangGraph checkpoint tables. Safe to call repeatedly
    (idempotent migrations) — but by contract we run this once at init."""
    with checkpointer() as cp:
        cp.setup()
