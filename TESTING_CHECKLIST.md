# TESTING_CHECKLIST.md — what to check before you trust a change

Gambit's first big project. This is the "did I think about this?" list, learned the hard way across the
build. Two parts: (A) the pre-flight checklist for EVERY change, and (B) the specific integration test
Seeker needs right now. Best-practice north star: **verify at the smallest, cheapest level that proves
it works, BEFORE spending money to prove it end-to-end.** The full run is the LAST check, not the first.

---

## A. PRE-FLIGHT CHECKLIST (run before every commit/push)

1. **Does it still build + pass the wiring test?** `.venv/bin/python tests/test_wiring.py` → ALL PASS.
   (This catches "an organ got orphaned." It does NOT catch "the organ produces junk.")
2. **Did I actually RUN the thing I changed** on real input — not just "does it import"? A component
   test (one LLM call, a few cents) is enough and is worth 100x a full run for finding bugs early.
3. **Unhappy path:** empty results, a dead API, a case with no people, a weird input — does it
   FAIL-OPEN (return nothing / skip) rather than crash? Everything in Seeker should fail-open.
4. **Cost:** does it add fetches or LLM calls? Fetches are dollars, questions are pennies. Is the
   expensive part CAPPED? (e.g. `SEEKER_INTERROGATION_LEADS`, `max_leads`, `top_k`.)
5. **Off-switch:** can I disable it without editing code — an env var or flag — if it misbehaves live?
6. **Safety guardrail (Seeker-specific):** if it touches people, does it still (a) never accuse a
   named person, (b) never promote a commentator/relative to victim, (c) keep unverified claims as
   unverified? Verify on real output, not by trusting the prompt.
7. **Second eyes:** did something other than the author look at it? Go check the actual source by hand
   (like the Podcast Index / Google checks that found real bugs), or spawn an audit subagent.
8. **Docs:** commit message says WHY, ORGANS.md + test_wiring updated in the same commit if it's a new
   organ, IDEA_LEDGER.md updated if an idea's status changed.

**The one we keep skipping:** #2 at the *system* level — "have I proven this works TOGETHER, not just
in pieces?" Unit-green + component-tested is necessary but not sufficient. See Part B.

---

## B. THE INTEGRATION TEST SEEKER NEEDS NOW

Six organs have been built/changed and **never run together**: the search-query adapter, the Mind
(wave-2), the pre-flight question gate, roster discovery, the interrogation loop, and per-person
question banks. Unit tests can't see their interaction. This is the real risk.

### Set the success bar FIRST (so the result is judgeable, not vibes)
Run against the missing-scientists case, fresh branch, all fixes live. PASS =:

**Retrieval & lanes**
- [ ] Web, primary, structured, YouTube lanes all fire (>0 findings each)
- [ ] Podcast lane fires (>0) AND pulls the dedicated "Missing Scientists" show (name-search fix)
- [ ] Citation-graph reads N/A (no papers), not DEAD
- [ ] No lane crashes; run completes exit 0, no watchdog abort, no false-abort

**Questioning loop (the new differentiator — the point of this run)**
- [ ] Wave-2 questions generated and driven (heartbeat shows `wave-2-questions`)
- [ ] Pre-flight gate rewrote at least one vague lead (check the lead list)
- [ ] Interrogation loop fired (heartbeat `interrogation`) and generated connection-questions —
      confirm at least one is an AFRL-overlap / co-author / communication-evidence style follow-up
- [ ] Per-person question bank drove ≥1 deep lead for a connection-involved subject
- [ ] Every generated question is a NEUTRAL probe — grep the question ledger, zero "did X kill/harm Y"

**Discovery**
- [ ] Roster discovery ran; if it promoted anyone, they're real case subjects (spot-check)
- [ ] Rejected list is populated and correct (commentators/politicians/orgs rejected WITH reasons)
- [ ] No garble/variant promoted as a phantom person (no "Melissa Cascio")

**People & report**
- [ ] ≤2 of the known roster read "unknown"; Eskridge = DECEASED (recency + per-entity profile fix)
- [ ] Quill report: canonical names throughout, no garbles, tier labels intact, no accusation
- [ ] The map renders every organ's section; contribution ledger shows no unexpected DEAD

**Cost & time**
- [ ] Completes under ~40 min and under ~$7 (log the actual spend from OpenRouter after)

### How to run it (once OpenRouter is topped up)
- One clean run, then HANDS OFF — score against the bar above, don't patch mid-flight.
- Watch the heartbeat (`runs/heartbeat.json`) for phase progress; the watchdog aborts a true stall.
- If it misses an item, that's a specific bug to fix cheaply (component test), not a reason to re-run
  the whole thing immediately. Re-run only to CONFIRM a fix, deliberately.

### What a good result proves
Not "the answer is right" — that a reader could go check. It proves the SYSTEM works together, and
that the interrogation loop actually deepens the investigation (connections → new questions → more
findings) instead of stopping at "here's what sources said."

---

## C. STANDING TEST COMMANDS (cheap, run anytime, no full investigation)
- Wiring: `.venv/bin/python tests/test_wiring.py`
- Query quality (graded, no fetch): `tools/query_grade.py` pattern
- Bias instrument self-check: `python -c "from seeker.bias_probe import calibrate; print(calibrate())"`
- A single organ live: import it and call it with one real input (pennies), as done throughout.
