# Seeker

**A persistent AI investigation engine — and an honest account of everything that broke while building it.**

Built with Claude over 30 days (2026-06-30 to 2026-07-30). This README leads with what I was trying
to do, how it failed, and what I actually got right — the failures are the longer section on purpose.
Everything below is verifiable in the code and in [`published/`](published/).

One thing up front, because it changes what's worth evaluating here: I tend bar, I'm learning to
code, and I didn't write most of this code. What I did was decide what to build, and keep asking why
it wasn't working until the real reasons surfaced. The [what I got right](#what-i-got-right) section
is about that, and it's the part I'd want read closely.

---

## What I was attempting

Most research tools answer questions that have answers. I wanted one for the questions that don't:
open cases, contested claims, clusters of events that may or may not be related.

The bar was specific and falsifiable: **return more valuable, connected information than you'd get
elsewhere for the same question, and be honest about what you don't know.** Not "solve it."

The design rule was one line, and I violated it constantly without noticing:

> **The model never judges its own quality. Verification always comes from outside.**

---

## How it failed

### It read 4% of its own evidence

A run gathered 677 findings. The conclusion was written from **28** of them.

The cause was `rows[:14]` inside one function — a constant chosen once and never revisited. 177
findings were never read by *anything*, including a fact about the central subject carrying 15
corroborating sources. It was never a size limit; the full set is ~24k tokens.

The same shape turned up in **six** organs: the ledger deciding what counted as "verified" from 14%
of the evidence, the pattern adjudicator answering the case's central question from 21%, the
question generator seeing 14 findings about a person who had 68.

**What I'd take from it:** a constant like `[:14]` is a design decision wearing a detail's clothes.
Sitting between your evidence and your model, it's the most consequential line in the file.

### A name is not an identity

"Matthew James Sullivan" returned Sullivan County, Tennessee. "Steven Garcia" returned Christian,
Melanie, Jonathan and Jose Ernesto Garcia. **254 of 705 findings were about different people who
happened to share a surname.**

It compounded: the component that gives thin cases extra attention saw a sparse file, searched
harder, pulled in more namesakes, counted them as depth, and declared the gap closed. The organ
built to help cold cases was poisoning them.

**What fixed it wasn't a better prompt.** It was arithmetic — a claim dating a death to 2013 cannot
describe someone known to have died in 2025.

### Prose is advisory; code is binding

The most repeated mistake here. Every rule written as an instruction to a model was eventually
ignored:

| rule as prose | outcome | rule as code | outcome |
|---|---|---|---|
| "disregard same-named strangers" | failed 3× | year-conflict arithmetic | caught immediately |
| "no atmospheric language" | next draft opened *"The hum that usually precedes the morning's frantic pace"* | regex ban list | caught immediately |
| "ask specific questions" | 63 commits of prompt-tuning | one `bad_question()` function | caught 40 of 40 |

### "Built" kept registering as "wired"

Nine capabilities were once found to have never run in production. I wrote a test to stop it
recurring — then it recurred three more times in two days, including the pipeline that produced the
first report to pass every check, which sat *beside* the run instead of inside it.

The test only failed when a function was called *nowhere at all* — including from its own test file.
So "tested" satisfied it.

### Editing an edit destroys the work

A report failed review, so I revised it. The revision failed differently, so I revised again. Eight
passes. The error count fell 6 → 3 → 2, which looked like convergence.

The finished document said "Status: Not recorded" for 11 of 13 people whose causes of death were
sitting in the same file. Each pass had quietly deleted true content it couldn't re-verify.

**A falling error count is not improving quality.** One corrective pass, then regenerate from source.

### Judging by a proxy instead of the thing itself

Four times in one day, in four disguises:

- Ranked citations by domain authority → an FBI cocaine-trafficking press release nearly landed in a
  report about missing scientists. Authoritative domain, irrelevant document.
- Counted surname matches as evidence "depth" → contamination read as progress.
- Checked "is this supported?" instead of "is this still here?" → a hollowed-out report passed eight
  gates.
- Named a folder `published/` and called the work published. It was a private repo.

---

## What I got right

**I asked the questions that found the bugs.** This is the part I'd most want read closely, because
I didn't write most of this code — I'm the one who kept asking why it wasn't working:

- *"Is the model reviewing 100% of the data in each organ?"* → found five more truncations after the
  first was fixed.
- *"If we're leaving data in the nodes and not reviewing it, what's the point of gathering it?"* →
  found that 26% of everything gathered was never read by anything.
- *"Did we ship anything yet?"* → caught a private repo being described as published.
- *"The questions are not good at all"* — repeated three times against reassurance → led to finding
  that three of four question generators couldn't see the research findings at all.

Each was a general question that turned one fix into five. The specific bugs mattered less than
noticing they were the *same* bug wearing different clothes.

**Two design calls that worked.** Compressing all evidence about one person into a single reviewable
case file — a container, not a summary, so triage happens inside it and nothing is lost to
compression. And using a competitor as a *contributor* rather than a *judge*: a judge caps you at
the judge's ceiling; a contributor only adds.

**Measured against something I didn't build.** Benchmarked against Perplexity's best research model,
scoring fixed before results were seen. Across six people spot-checked by hand, Perplexity surfaced
nothing this system's map didn't already hold, and independently corroborated every claim checked.

**Gates that can say no.** The publisher-reviewer refused four consecutive reports. It was right
every time.

---

## What still doesn't work

- **Speed.** ~90 minutes per investigation. Perplexity's mid-tier model matched its *coverage* in 23
  seconds. Depth and provenance are the edge — but 230× is not free.
- **Discovery.** It was handed its 13 subjects. It has never assembled a roster unaided.
- **Determinism.** The connections engine returns 5–7 links on identical input. I read differences as
  signal more than once before checking.
- **Size.** 11,334 lines across 65 modules; 234 commits, 57 of them repairs (24%). The recurring
  bugs are a symptom of a system too large to hold in one head.

## Status

One investigation has passed every check and is in [`published/`](published/) — 13 people, 37
relevance-checked citations. It required **no new searching**: the evidence had been gathered days
earlier and simply never read.

I'm rebuilding from these notes. The retrieval engine is worth keeping; the ~7,000 lines of analysis
scaffolding around it is where every recurring defect has lived.

---

## Stack

Firecrawl (primary search/fetch) · Exa + Jina (fallback) · Pinecone (vector store) · Jina v3
embeddings · OpenRouter multi-model + Groq · OpenAlex (citation graph) · YouTube transcripts +
Podcast Index

```bash
cp .env.example .env      # your own keys
pip install -r requirements.txt
python tests/test_wiring.py     # asserts every organ actually fires in a real run
```

## A note on the case in `published/`

It concerns real people who are missing or dead. Every claim is tied to a source, unverified
material is labelled unverified, and the report states plainly that a coordination claim circulates
and is unproven. That sentence caused the reviewer to withhold approval; I kept it, because removing
it would satisfy the gate and tell the reader less. The disagreement is recorded rather than edited
away.

Nothing in it should be read as an accusation against any person.
