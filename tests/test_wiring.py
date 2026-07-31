"""Wiring test — mechanically enforces ORGANS.md (the Integration Contract).

Born 2026-07-18, after the audit found 9 built-but-never-firing capabilities: the flagship run used
none of the intelligence/presentation organs, and nobody noticed because 'done' lived in narrative,
not in a test. This suite makes the wiring truth mechanical:

  1. FLAGSHIP: every organ registered as flagship must have a literal call site in the flagship path.
  2. ORPHAN GUARD: every public function in the organ modules must be CALLED somewhere outside its
     own module, OR be explicitly registered (standalone-by-design / pending-integration / helper).
     A new unregistered orphan turns the suite red — in the same commit it's born.

Run: .venv/bin/python tests/test_wiring.py   (stdlib only; static scan, no network)
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "seeker")
CLI = os.path.join(ROOT, ".claude", "skills", "seeker-investigate", "investigate.py")

# ---- 1. FLAGSHIP registry: (file, required call-site pattern) — mirrors ORGANS.md ----
FLAGSHIP = [
    ("director.py",            "harvest_entities("),        # brief 29 entity harvest
    ("director.py",            "ach_score("),               # ACH
    ("director.py",            "claim_ledger("),            # ledger + lean
    ("director.py",            "synthesize("),              # synthesis
    ("director.py",            "_open_threads("),           # open threads
    ("director.py",            "check_completeness("),      # completeness gate
    ("director.py",            "cluster_entities("),        # display roster resolution
    ("director.py",            "_drive_leads("),            # parallel leads
    ("hunt/hunt.py",           "podcast.gather("),          # podcast lane
    ("hunt/hunt.py",           "youtube.gather("),          # youtube lane
    ("hunt/hunt.py",           "seek_primary("),            # H4
    ("hunt/hunt.py",           "chase_citation_graph("),    # H6
    ("synthesis.py",           "_normalize_names("),        # keystone chokepoint
    ("synthesis.py",           "_demote_spoken_only("),     # spoken-word-as-leads dataflow
    ("director.py",            "find_connections("),        # Connections Engine (integration #27)
    ("director.py",            "disagreement_map("),        # disagreement (integration #27)
    ("director.py",            "_quill.report("),           # Quill reporting layer (integration #27)
    ("director.py",            "_quill.critique("),         # Quill editor gate (integration #27)
    ("director.py",            "top_corroborated("),        # corroboration ranking (integration #27)
    ("director.py",            "_mapgen.write_map("),       # auto-map capstone (integration #27)
    ("director.py",            "adjudicate_claimed_patterns("),  # Pattern-Claim Adjudicator (task #28)
    ("director.py",            "watchdog.start("),          # always-on stall backstop (task #31)
    ("director.py",            "watchdog.beat("),           # progress heartbeat (task #31)
    ("director.py",            "entity_profiles("),         # per-person mini-dossier (task #32)
    ("director.py",            "form_question("),           # question-former front door (task #36)
    ("director.py",            "generate_next_questions("), # the Mind: wave-2 questioning (task #33)
    ("director.py",            "preflight_gate("),          # question quality gate (task #33)
    ("director.py",            "discover_roster("),         # roster discovery (task #34)
    ("director.py",            "questions_from_connections("),  # interrogation loop (task #35)
    ("director.py",            "question_bank("),           # per-person question bank (task #35)
    ("director.py",            "findings_per_entity("),     # depth equalization: measure per-person (task #36)
    ("director.py",            "set_case_anchor("),         # run-scoped case anchor for structured lane (task #37)
    ("director.py",            "_pubrev.review("),          # Publisher-Reviewer honesty gate (task #37)
    ("quill.py",               "voice_violations("),        # voice rule enforced as CODE, not prompt (task #42)
    ("quill.py",               "_strip_voice("),            # targeted deletion pass, re-fact-checked (task #42)
    ("hunt/seeker_agent.py",   "_anchor_for("),             # bulk search lanes anchor per-person (task #41)
    ("director.py",            "set_identity_cards("),      # cards reach the lanes that do the searching (task #41)
    ("director.py",            "build_cards("),             # identity cards: per-person namesake anchor (task #41)
    ("director.py",            "_identity.screen("),        # identity screen: quarantine year-contradictions (task #41)
    ("director.py",            "retry_queries("),           # reconstructed search after a quarantine (task #41)
    ("director.py",            "format_cards("),            # cards printed LIVE so a wrong card is catchable (task #41)
    ("director.py",            "_organ_failed("),           # a skipped organ is LOGGED, not lost
    ("director.py",            "_wire.build("),             # wire-dossier write-up IS the run (task #38)
    ("director.py",            "_cf.triage_all("),          # every finding reviewed before write-up
    ("director.py",            "_contrib.contribute("),     # contribution lane fires in the run
    ("director.py",            "_syn.all_findings("),       # lossless read — no relevance ceiling
    ("wire_report.py",         "profile_fidelity("),        # substance guard fires inside the write-up
    ("wire_report.py",         "count_fidelity("),          # aggregate-arithmetic guard
    ("case_files.py",          "triage_file("),             # per-file triage actually runs
    ("interrogate.py",         "evidence_for("),            # question_bank reads the findings first (task #38)
    ("director.py",            "_challenge_checkpoint("),
    ("director.py",            "suggest_next_questions("),  # hand the next question back to the human (task #40)
    ("challenger.py",          "course_correction("),      # gate ADDS corrective questions on drift (task #39)   # Challenger gate fires IN the run (task #39)
    ("director.py",            "follow_ups("),              # the follow-up hop: an answer raises the next question (task #38)
    ("mind/mind.py",           "_question_rules("),         # Mind prompt carries the question-shape rules (task #38)
    ("quill.py",               "synthesis_model("),         # bias-card -> writer routing, loop closed (task #37)
    ("hunt/hunt.py",           "seeker_agent.seek_firecrawl("),  # 2nd search engine, Firecrawl lane (task #35)
    ("hunt/hunt.py",           "adversarial.pre_flight("),  # adversarial gate (audit fix: was unasserted)
    ("hunt/hunt.py",           "adversarial.post_flight("), # adversarial post-flight
    ("hunt/seeker_agent.py",   "_sq.for_engine("),          # search-query adapter, web lane
    ("hunt/seeker_agent.py",   "_sq.strip_instructions("),  # search-query adapter, primary lane
    ("recon/youtube.py",       "_sq.for_engine("),          # search-query adapter, youtube lane
    ("recon/youtube.py",       "_firecrawl_transcript("),   # IP-block bypass: transcript via Firecrawl (task #37)
]

# ---- 2. Modules scanned by the orphan guard: ALL of src/seeker (audit fix 2026-07-21). ----
# The old hand-list covered 11 root modules — and the Mind's question generator hid ORPHANED in
# mind/ for weeks precisely because the guard never looked there. Walk everything; a hand-list of
# where to look for orphans is itself an orphan-shaped blind spot (Noor).
def _organ_modules() -> list:
    out = []
    for base, _, files in os.walk(SRC):
        for fn in files:
            if fn.endswith(".py") and fn != "__init__.py":
                out.append(os.path.relpath(os.path.join(base, fn), SRC))
    return sorted(out)

# Registered exceptions — MUST mirror ORGANS.md. Pending may only SHRINK (integration build).
SUPERSEDED = {
    # recon_pass.run_recon was brief-01's multi-source sweep. hunt.hunt does the same job with the
    # Firecrawl/Exa/YouTube/podcast lanes and IS what every run calls. Wiring recon_pass now would
    # add a second, older sweep of the same ground — worse than leaving it dark. Declared here so
    # "nothing is left unwired" stays TRUE rather than quietly false.
    "run_recon",
}
PENDING_INTEGRATION = {
    "qualify",        # search_queries: place/date query enrichment — needs known-facts plumbing (#34)
    "cited_by",       # scholar: forward citation-chaining — built, never wired (declared honestly)
}
STANDALONE_BY_DESIGN = {
    "challenge", "format_report", "course_correction",   # challenger gate — called by ME at checkpoints + tools, not by the flagship
    "quick_take", "resume", "investigation_state", "register",
    "calibrate", "run_lean_card", "write_lean_card",   # bias lean-card research tool (tools/run_bias_card.py)
    "objective_from_choice",                            # goal-generator choice flow (--suggest-goals)
    "all_entries", "all_scores", "health_check",        # inspection/debug API surface
    # loop-pipeline graph nodes: invoked by NAME-reference (add_node("hunt", hunt_node)), which the
    # call-pattern regex cannot see — verified live in the no-flag loop mode, not orphans:
    "mind_node", "hunt_node", "recon_node", "gap_node", "build_graph", "setup_once",
    "chase_recursive",                                  # legacy H6 v1 — superseded by chase_citation_graph
}
HELPERS_OK = {"proper_names", "resolve_entities", "cluster_entities", "standard_label",
              "run_investigation", "build_case_plan", "targeted_questions", "build_map", "write_map",
              "ensure_table", "is_wordcount_suspect"}   # schema-setup / internal validator helpers

_fails = []


def check(name, cond, hint=""):
    print(("  ok  " if cond else "FAIL  ") + name + (f"\n        -> {hint}" if (hint and not cond) else ""))
    if not cond:
        _fails.append(name)


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


def test_flagship_call_sites():
    for rel, pattern in FLAGSHIP:
        text = _read(os.path.join(SRC, rel))
        check(f"flagship: {pattern:28s} fires in {rel}", pattern in text,
              "a flagship organ lost its call site — the run no longer uses it")


def test_orphan_guard():
    corpus = {}
    for base, _, files in os.walk(SRC):
        for fn in files:
            if fn.endswith(".py"):
                corpus[os.path.join(base, fn)] = _read(os.path.join(base, fn))
    corpus[CLI] = _read(CLI)
    # legit callers also live OUTSIDE src: root runner scripts (run_recon.py, run_failure_recovery.py)
    # and dev tools (tools/*.py). Scan them too, or their callees read as false orphans (audit fix).
    import glob
    for extra in glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "tools", "*.py")):
        corpus[extra] = _read(extra)
    registered = PENDING_INTEGRATION | STANDALONE_BY_DESIGN | HELPERS_OK | SUPERSEDED
    # NOTE (2026-07-30): tools/*.py are loaded into `corpus` as CALLERS only — nothing checks
    # whether a TOOL is itself ever run. That is how the Obsidian exporter sat unused for three
    # weeks with this suite green, and Chris had to ask. Tools are human-invoked by design, so
    # they are not orphans; but the flagship registry above is now the only thing standing between
    # "built" and "fires", which is why every new organ must be added to it IN THE SAME COMMIT.
    for mod in _organ_modules():
        mod_path = os.path.join(SRC, mod)
        text = corpus.get(mod_path, "")
        for fname in re.findall(r"^def ([a-z][a-z0-9_]*)\(", text, re.M):
            # orphan = never INVOKED anywhere in src/CLI (its own def/alias lines don't count).
            # Same-module calls DO count — flagship-vs-side-door is the FLAGSHIP section's job.
            called = any(len(re.findall(r"\b" + fname + r"\(", body)) >
                         len(re.findall(r"def " + fname + r"\(", body))
                         for body in corpus.values())
            ok = called or fname in registered
            check(f"orphan-guard: {mod}:{fname}", ok,
                  "built-but-unwired and UNREGISTERED — wire it, or add it to ORGANS.md + this "
                  "registry in the SAME commit (the Integration Contract)")


def test_no_run_killers():
    """Static scan for the RUN-KILLER class: a name read before it is bound.

    Twice now this has destroyed a flagship run at the finish line — `_os.environ` used 3600 lines
    above its import (caught by eye, pre-v16), and `profiles` read by the Quill call 51 lines above
    its assignment (NOT caught; killed v19 after 1h29m of completed searching). Both were pure
    ordering mistakes that a two-second static pass reports instantly, and both survived because
    'it imports fine' was mistaken for 'it runs'. Python does not resolve these until execution
    reaches the line, so a crash in the final assembly costs the whole run.

    Only the fatal diagnostics fail the suite — unused imports and f-string nits are style, and a
    gate that cries about style gets ignored, which is how it misses the one that matters."""
    import subprocess
    try:
        out = subprocess.run([sys.executable, "-m", "pyflakes", SRC],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception as e:
        check("run-killer scan: pyflakes available", False, f"could not run pyflakes ({e}) — "
              "install it: .venv/bin/python -m pip install pyflakes")
        return
    fatal = [ln for ln in out.splitlines()
             if "undefined name" in ln or "before assignment" in ln]
    check("run-killer scan: no name read before it is bound", not fatal,
          "; ".join(fatal[:5]))


if __name__ == "__main__":
    print("test_flagship_call_sites")
    test_flagship_call_sites()
    print("test_orphan_guard")
    test_orphan_guard()
    print("test_no_run_killers")
    test_no_run_killers()
    print(f"\n{'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + ', '.join(_fails)}")
    sys.exit(1 if _fails else 0)
