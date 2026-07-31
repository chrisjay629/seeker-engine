# Building Many Parts Into One System — the checklist

*A rule-of-thumb sheet for building multiple components ("organs") into any app or database, so you
never end up with a pile of working parts that don't add up to a working product. Written plainly —
for anyone learning to code. Born 2026-07-18 after we built ~20 organs and half of them never fired.*

---

## The core trap

You build Part A. It compiles, a small test passes, you demo it once → you *feel* done → you move to
Part B. Repeat 20 times. Each part works **alone**. Then you run the real thing and half of them
never actually run, because "connect it to the main flow" was never on the checklist. The parts were
fine. The **integration** was never built. That's the #1 way ambitious projects quietly fail.

## "Built" is not "Done." Done means passing FOUR gates.

Say this out loud for every component:

| Gate | The question | How you PROVE it (not just believe it) |
|---|---|---|
| **1. WIRED** | Is it connected — does anything actually *call* it? | Search the codebase for its name. If the only place it appears is where it's *defined*, it's an orphan. `grep "my_function("` — count the hits outside its own file. |
| **2. FIRING** | Does it run in the REAL pipeline, or only in a test / a side-door? | Trace the main entry point (the one command a user runs) and confirm the call is on that path — not in a `--special-flag` nobody uses. |
| **3. CONTRIBUTING** | When it fires, does it produce meaningful output — or nothing? | Make the run *report what each part added*. A part that "runs" but returns 2 results out of 800 is technically alive and practically dead. If you can't see its contribution, you can't trust it. |
| **4. WHOLE** | Does the FULL design work end-to-end, all parts together, on real input? | ONE real end-to-end run, start to finish, and look at the actual output. Unit tests lie about this — they test parts in isolation, which is exactly the thing that was fine. |

**A green unit test proves gate 1 at best. It says nothing about 2, 3, or 4.** That's the whole lesson.

## Make the truth MECHANICAL, not remembered

Humans (and AIs) forget, and worse, *narrate* — "yeah that's wired in" when it isn't. So don't rely on
memory or status updates. Build machines that check for you and fail loudly:

1. **A registry** — one file listing every component and its honest state (wired / standalone / pending
   / not-built). Single source of truth. In this project: `ORGANS.md`.
2. **A wiring test** — automatically fails the build if a component has no call site and isn't
   registered as intentionally-standalone. A new orphan turns the suite red *in the commit that made
   it*. In this project: `tests/test_wiring.py`.
3. **A contribution ledger in the OUTPUT** — every real run prints what each part actually added
   (`Citation-graph: 2 findings [weak]`, `Connections: ABSENT (not wired)`). Now "is it firing?" is a
   question you answer by *looking at the result*, not by trusting anyone.

The rule: **if a check only happens when someone remembers to look, it will eventually not happen.**
Put the check where it fires automatically — in the tests that run every time, in the output you read
every time.

## Other hardwired rules (learned the hard way)

- **Enforce rules in the DATAFLOW, not in instructions.** A rule written as a note/prompt drifts and
  gets ignored. A rule enforced by the code path (or a test) holds. ("Treat podcasts as leads not
  facts" failed as a prompt; worked the moment it was a step in the pipeline.)
- **Verify before you claim. "Show me the call site."** Before saying a thing works, produce the
  evidence — the line where it's called, the number it produced. No evidence = not done.
- **One end-to-end run beats ten unit tests** for catching integration failure. Do both, but never skip
  the whole-run.
- **A registry entry and its test assertion ship in the SAME commit as the new component.** Not "later."
  Later never comes.
- **Absence must be visible.** "We didn't build X" and "X is built but not wired" are different, and
  both must show up somewhere honest — not be silently missing.

## The one-line version

> **Built ≠ wired ≠ firing ≠ contributing ≠ the-whole-thing-working.** Prove all five, mechanically,
> or you have a drawer of nice parts and no product.
