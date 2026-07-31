# ORGANS.md — the wiring registry (single source of truth)

**The Integration Contract:** an organ is NOT done until it (a) fires in the flagship `--director`
run, (b) is visible in that run's output, and (c) `tests/test_wiring.py` asserts its call site — OR
it is explicitly registered below as standalone-by-design or pending-integration. "Built" ≠ "done."
This file exists because we shipped 9 capabilities that never fired in a real run (2026-07-18 audit).

## ✅ FLAGSHIP — fires in every `--director` run (verified call sites)
| Organ | Where it fires |
|---|---|
| Hunt + all sensor lanes (web/primary/structured/YouTube/podcast) | director → hunt() |
| Citation-graph H6 (OpenAlex) + query expansion + H1 desc mining | hunt() with_expansion — chases real PAPERS; 0 findings on a no-paper case reads as **N/A**, not DEAD (author-name seeding rejected: false-attributes, see scholar.py) |
| Transcript-first entity harvest (brief 29) | director step 0 |
| seed_entities guaranteed roster + completeness gate | director step 2b / 5 |
| Parallel leads + parallel harvest + parallel write-up (#18/#20) | director |
| ACH hypothesis competition | director step 4 |
| Claim ledger + directional lean (brief 30) | director step 4 |
| Synthesis + neutrality protocol | director step 4 |
| Entity resolution: chokepoint normalization + spoken-word demotion + display roster | gather_findings / director |
| Entity profiles — per-person mini-dossier (status/cause/detail), grounded, no accusation (task #32) | director step 5 → entity_profiles() |
| The Mind — wave-2 questioning: reads wave-1 findings, generates scored frontier questions (task #33; orphaned since brief 05, now firing) | director step 3b → generate_next_questions() |
| Question-Former — panel(3 labs) + brief-17 doctrine + grounded fact-check forms the ROOT question; corrections listed, never silent (task #36) | director step 0a → question_former.form_question() |
| Interrogation loop — connections spawn NEW questions + per-person question banks, chased before write-up (task #35) | director step 3d → interrogate.questions_from_connections() / question_bank() |
| Roster discovery — finds case subjects NOT in the supplied roster; role-classifies each so a commentator/relative is never promoted to victim (task #34) | director step 3c → discovery.discover_roster() |
| Completeness gate | director step 5 — now runs on EVERY run (the `if not seeds` gate silently disabled discovery on all seeded runs) |
| Pre-flight question gate — grade leads A-F BEFORE fetch spend, rewrite C/F (task #33) | director step 2c → search_queries.preflight_gate() |
| Search-query adapter — strip scaffolding, name+angle fan-out, per-engine register | seek()/seek_primary()/youtube.gather()/podcast_query() |
| Open-threads generator (fixed) | director step 4 |
| Connections Engine (find_connections) — Seeker's OWN link analysis | director step 4 (integration #27) |
| Disagreement map + what_would_resolve | director step 4 (integration #27) |
| Quill report + notable threads + fact-fidelity guard + critique | director step 4b (integration #27) |
| Corroboration ranking (top_corroborated) | director step 5 (integration #27) |
| Pattern-Claim Adjudicator (adjudicate_claimed_patterns) — who claims a pattern + does it hold up | director step 4 (task #28); cross-refs Connections + claim-ledger; 5th verdict `unresolved-notable`; N/A (not DEAD) when a case has no pattern-claims |
| Auto-generated shareable map (mapgen) | director capstone (integration #27) |
| Organ-mix provenance display + CONTRIBUTION LEDGER | _render_dossier |
| Rate governor (+ hard timeout guard) | all fetch/LLM call paths |
| Bounded fetch (wall-clock deadline + byte cap on streamed reads) | fetch.py jina/firecrawl/wayback |
| Run watchdog — progress heartbeat + dump-and-abort on 10-min stall (task #31) | director start / per-phase beat / stop |
| Adversarial pre/post-flight | hunt() |

## 🚪 STANDALONE-BY-DESIGN — separate CLI modes (legitimate, not orphans)
| Organ | Door |
|---|---|
| Quick take | `--quick` |
| Resume / investigation state | `--resume` / `--state` |
| Goal generator | `--suggest-goals` |
| Bias lean-card (bias_probe) — measures synthesis-writer lean; feeds routing + Publisher-Reviewer | research tool, run occasionally; NOT in flagship |

## 🔴 PENDING-INTEGRATION (declared honestly; may only SHRINK — enforced by test_wiring)
| Organ | State |
|---|---|
| KB-first reuse | declared loop-only (compounding loop); director bypasses by design (fresh diligence) |
| search_queries.qualify — place/date query enrichment | built 2026-07-21; needs known-facts plumbing from the map into queries (task #34) |
| scholar.cited_by — forward citation-chaining | built, never wired; declared by the 2026-07-21 full audit |

**Audit note (2026-07-21):** the orphan-guard now walks ALL of src/seeker (the old 11-module hand-list
let the Mind hide orphaned in mind/ for weeks) and scans root runner scripts + tools/ as legit callers.
Full-audit verdict: no undeclared orphans remain; loop-graph nodes (invoked by name-reference) and
inspection APIs are registered standalone.

## ⬜ NOT BUILT (tracked tasks, never claimed as shipped)
connect-while-gathering (#25 mode A) · ffmpeg full-episode chunking (#17) · adaptive rate governor
(#19) · SEC/CourtListener lanes (#22) · retrieval benchmark (#21) · garble correction (#26)

**Maintenance rule:** new organ ⇒ add a row HERE + a call-site assertion in `tests/test_wiring.py`
in the SAME commit, or the suite goes red.
