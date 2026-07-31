# Seeker

A persistent AI investigation engine built to ask better questions than a human researcher would,
reach knowledge that is locked or scattered, connect dots no one has connected before, and free what
it finds for the commons.

Built by Christopher Jauregui — a bartender learning to code — with Claude.

**Read the [honest status](#honest-status) before the architecture.** This repo is public so the
failures are public too. I plan to rebuild it, and the account below is what the rebuild should
start from.

## The Governing Spine

> **The model never judges its own quality. Verification always comes from outside.**

Every design choice traces back to this. It is also the principle I violated most often without
noticing — see [what went wrong](#what-went-wrong-and-what-it-cost).

## Architecture — Three Organs

- **The Seeker** — mechanical & cheap. Goes out, reads sources, returns a finding plus its citation.
  Skims cheap, deep-reads only survivors.
- **The Memory** — external, always-on, cheap. Files, stores, labels, indexes, retrieves. Never thinks.
- **The Mind** — the only part that thinks. All comprehension happens here, so cost is concentrated
  in one place.

Around that spine sit the analysis organs (synthesis, claim ledger, connections, disagreement map,
competing-hypotheses scoring, pattern adjudication, per-person profiles) and the gates (question
quality, an adversarial Challenger, identity/namesake checks, voice, fidelity, and a
publisher-reviewer that can refuse to publish).

One finished investigation is in [`published/`](published/).

---

## What went wrong, and what it cost

This is the useful part.

### Everything read a fraction of what it gathered

The worst bug in the project, found late by asking a plain question: *is the model actually
reviewing all the data?*

It wasn't. A run gathered 677 findings. Then:

| stage | findings it saw |
|---|---|
| retrieved by any organ | 500 |
| **placed in the synthesis prompt** | **28** |

**The conclusion of an entire investigation was written from 4% of the evidence.** The cause was
`rows[:14]` inside one function — a number chosen once and never revisited. 177 findings were never
read by anything at all, including a fact about the central subject carrying 15 corroborating
sources.

It was never a size limit. All 677 findings are about 24k tokens.

The same shape appeared **six times** in different organs: the claim ledger deciding what counted as
"verified" from 14% of the evidence; the pattern adjudicator answering the case's central question
from 21%; the question generator seeing 14 findings about a person who had 68.

**Lesson:** a constant like `[:14]` is a design decision disguised as a detail. Sitting between your
evidence and your model, it is the most important line in the file.

### A name is not an identity

Searching "Matthew James Sullivan" returned Sullivan County, Tennessee. Searching "Steven Garcia"
returned Christian, Melanie, Jonathan and Jose Ernesto Garcia. Of 705 findings reviewed, **254 were
about different people who happened to share a surname.**

It fed a loop: the depth-equalizer saw a thin file, spent extra searches filling it, pulled in more
namesakes, counted them as depth, and concluded the gap had closed. The organ built to give cold
cases *more* attention was poisoning them.

**Lesson:** the fix that worked wasn't a better prompt. It was arithmetic — a claim dating a death
to 2013 cannot describe someone known to have died in 2025.

### Prose is advisory. Code is binding.

The most repeated failure here. Every rule written as an instruction to a model was eventually
ignored:

- A paragraph telling the writer to disregard same-named strangers → failed three times. A
  year-arithmetic check caught them immediately.
- A prompt banning atmospheric language → the next draft opened with *"The hum that usually precedes
  the morning's frantic pace."* A regex ban list caught it.
- A rule that questions be specific → 63 commits of prompt-tuning. One `bad_question()` function
  caught 40 of 40 instantly.

**Lesson:** if a rule matters, make it a check that can fail.

### Built ≠ wired

Nine capabilities were once found to have never fired in a real run. A test was written to prevent
recurrence — and it happened three more times in two days, including the write-up pipeline that
produced the first report to pass every gate, which sat *beside* the run instead of in it.

The test only failed when a function was called *nowhere*, including from its own test file. So
"tested" registered as "wired."

**Lesson:** integration must be asserted explicitly, in the same commit as the build. A green suite
is only as honest as what it checks.

### Editing an edit destroys the artifact

A report failed its reviewer, so it was revised. The revision failed differently, so it was revised
again. Eight passes. Flag counts fell 6 → 3 → 2, which read as convergence.

The finished artifact said "Status: Not recorded" for 11 of 13 people whose documented causes were
in the same file. Each pass was re-verified against a retrieval slice, and each quietly deleted true
content it couldn't re-find.

**Lesson:** a falling error count is not improving quality. Check the substance after every pass.
One corrective pass maximum, then regenerate from source.

### Judging by a proxy instead of the property

Made four times in one day, in four costumes:

- Ranked citations by domain authority → an FBI cocaine-trafficking press release nearly went into
  a report about missing scientists. Authoritative domain, irrelevant document.
- Counted surname matches as evidence "depth" → contamination read as progress.
- Checked "was this supported?" instead of "is this still here?" → a hollowed-out report passed
  eight gates.
- Named a folder `published/` and called the work published. It was a private repo.

**Lesson:** measure the thing you care about, not the thing that correlates with it.

---

## What worked

- **The research engine.** A hard 13-person investigation produced 677 sourced findings across five
  source types. Benchmarked against Perplexity's best research model: across the six people
  spot-checked by hand, **Perplexity surfaced nothing Seeker's map did not already hold**, and
  independently corroborated every Seeker claim checked. (Six of thirteen — not the whole roster.
  Stated narrowly on purpose.)
- **Deterministic gates.** Every check that actually caught something was arithmetic or a regex —
  never a model asked to be careful.
- **A reviewer that can say no.** It refused four consecutive reports. Correct each time.
- **Case-file triage.** Grouping findings per person with a recorded verdict made full review
  affordable and isolated contamination automatically.

## What did not work

- **Speed.** ~90 minutes per investigation. Perplexity's `sonar-pro` matched Seeker's *coverage* in
  23 seconds. Seeker's edge is depth and provenance — but 230× is not free.
- **Discovery from scratch.** Seeker was handed its 13 names. It has never demonstrated assembling a
  roster unaided. (Perplexity, asked the same question without names, found 6 of 13.)
- **Determinism.** The connections engine returns 5–7 links on identical input. Counts are soft, and
  I over-read differences as signal more than once.
- **Complexity.** ~10,000 lines across 59 modules; 216 commits, a quarter of them repairs. The
  recurring bugs are a symptom of a system too large to hold in one head.

## Honest status

**Working:** the engine gathers well; identity checks hold; every organ now reads 100% of the
evidence; one investigation has passed every gate and been approved for publication.

**Not working:** it is slow, larger than it needs to be, and the same class of bug keeps reappearing
somewhere new. The reporting layer was rebuilt once and still needed three mechanical fixes after.

**Next:** a rebuild starting from these notes. The engine is worth keeping. The ~7,000 lines of
analysis-and-reporting scaffolding around it is where every recurring defect has lived.

On the original Phase 1 exit criteria: *"The engine feels like it's working is not an exit criterion.
External ground truth plus demonstrated failure recovery is."* The Perplexity benchmark is the
external ground truth. This README is the failure recovery, published rather than buried.

---

## Tech stack (as actually built)

| Layer | Tool |
|---|---|
| Search + fetch (primary) | Firecrawl |
| Search + fetch (fallback) | Exa, Jina |
| Vector store | Pinecone |
| Embeddings | Jina v3 (1024-d) |
| Mind / analysis | OpenRouter (multi-model), Groq for speed |
| Spoken word | youtube-transcript-api, Podcast Index |
| Scholarly | OpenAlex |

*Earlier plans named LangGraph and n8n as the orchestrator and Exa as primary search. The working
system uses a direct Python director and Firecrawl-first retrieval; the loop-mode graph exists but
is not the flagship path. Documented here because a stale stack table is its own small lie.*

## Running it

```bash
cp .env.example .env      # add your own keys
pip install -r requirements.txt
.venv/bin/python tests/test_wiring.py      # asserts every organ actually fires
```

## A note on the case in `published/`

It concerns real people who are missing or dead. Every claim is tied to a source, unverified
material is labelled unverified, and the report states plainly that a coordination claim circulates
and is unproven. That sentence caused the reviewer to withhold approval; it was kept deliberately,
because cutting it would satisfy the gate and tell the reader less. The disagreement is recorded
rather than edited away.

Nothing in it should be read as an accusation against any person.
