"""Central config — loads .env, exposes keys and the Recon source roster.

Verified live 2026-07-01. Model IDs live-checked against OpenRouter 2026-07-02
(Cipher). Override the roster via env if OpenRouter IDs drift.
"""
from __future__ import annotations

import os
import socket
from pathlib import Path

# PROCESS-WIDE SOCKET FLOOR (2026-07-19): the systemic backstop for the whole class of "unbounded
# network read hangs the run." Any socket that does NOT set its own timeout inherits this default, so
# a third-party SDK we don't control (Pinecone, Groq, Supabase, ...) can never block forever on a
# stalled read — it raises after 180s and the caller fails open. Our own long calls (Groq whisper
# transcription) set their own explicit timeout and are UNAFFECTED. This is the floor; the run
# watchdog (10-min abort) is the ceiling; explicit per-call timeouts are the tight inner bound.
socket.setdefaulttimeout(180)

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"


def _load_env() -> None:
    """Minimal .env loader (no dependency). Does not overwrite real env vars."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_env()


def require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"Missing {name} in environment / .env")
    return val


# --- Keys ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY", "")
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
# Podcast Index API (FREE) — episode/feed discovery by topic (sha1 auth)
PODCASTINDEX_API_KEY = os.environ.get("PODCASTINDEX_API_KEY", "")
PODCASTINDEX_API_SECRET = os.environ.get("PODCASTINDEX_API_SECRET", "")

# --- Recon Pass source roster ---
# Distinct frontier voices via OpenRouter. Diversity across providers is what
# produces genuine disagreement signal (blueprint). Mid/flagship mix keeps the
# Phase 1 sweep affordable under the $10 OpenRouter cap.
# Recon panel — DIVERSE voices to expose disagreement, not peak quality. Opus 4.6 was pulled
# (2026-07-19 routing audit): it was ~40% of the OpenRouter bill yet only casts one vote in a
# diversity panel. Swapped to Sonnet 4.5 — a capable Claude voice at a fraction of the cost. The
# panel keeps five distinct labs (Anthropic / OpenAI / Google / xAI / DeepSeek).
OPENROUTER_RECON_MODELS = os.environ.get(
    "OPENROUTER_RECON_MODELS",
    ",".join([
        "anthropic/claude-sonnet-4.5",
        "openai/gpt-4.1",
        "google/gemini-2.5-flash",
        "x-ai/grok-4.3",
        "deepseek/deepseek-chat-v3.1",
    ]),
).split(",")

GROQ_RECON_MODEL = os.environ.get("GROQ_RECON_MODEL", "llama-3.3-70b-versatile")
PERPLEXITY_RECON_MODEL = os.environ.get("PERPLEXITY_RECON_MODEL", "sonar")

# Research Extractor uses a cheap model — comprehension-lite, not the Mind. This is the VOLUME tier:
# hundreds of grunt calls per run (extract a page, "same claim or not?"), so cheapest-capable wins.
EXTRACTOR_MODEL = os.environ.get("EXTRACTOR_MODEL", "openai/gpt-4.1-mini")

# REASONING tier (2026-07-19 routing audit): the verdict-deciding organs — synthesis, ACH, claim
# ledger, connections, disagreement, Pattern-Claim — were quietly running on the cheap EXTRACTOR_MODEL
# because they all route through _cheap_json. They are only ~10 calls per run, so a stronger model here
# costs pennies but sharpens the actual conclusions. (The synthesis/Quill CHOICE stays open pending the
# bias lean-card — this just stops the verdict from being written by a grunt model.)
REASONING_MODEL = os.environ.get("REASONING_MODEL", "openai/gpt-4.1")

REQUEST_TIMEOUT = int(os.environ.get("SEEKER_REQUEST_TIMEOUT", "60"))
