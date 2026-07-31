"""Preview EVERY question Seeker would ask — without spending a single fetch.

WHY (Gambit, 2026-07-27): "Is there any way we can stop the search as soon as we see what questions
it's generating?" Until now the only way to judge the questions was to pay for a full run (~450
credits, ~1h45m) and read the dossier afterwards. That is a terrible feedback loop for the thing
that determines everything downstream.

This harness runs the REAL generators against an EXISTING branch's findings and prints what each
would ask — no web/YouTube/podcast fetching, no map writes. A few cheap LLM calls.

  .venv/bin/python tools/preview_questions.py missing-scientists-v14
  .venv/bin/python tools/preview_questions.py missing-scientists-v14 --person "Amy Eskridge"

Each question is graded by the same deterministic gate the pipeline uses, so a bad one is visible
as bad (✗ with the reason) rather than quietly driving a fetch.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from seeker import interrogate as I               # noqa: E402
from seeker import search_queries as sq           # noqa: E402
from seeker.director import build_case_plan, targeted_questions   # noqa: E402
from seeker.memory.memory_map import MemoryMap    # noqa: E402

ROSTER = ["William Neil McCasland", "Monica Jacinto Reza", "Anthony Chavez", "Steven Garcia",
          "Carl Grillmair", "Nuno Loureiro", "Jason Thomas", "Melissa Casias", "Frank Maiwald",
          "Michael David Hicks", "Matthew James Sullivan", "Amy Eskridge", "Joshua LeBlanc"]
SUBJECT = ("The 2026 'missing scientists' case: for EACH named individual, verified status and "
           "documented cause — and is there a genuine coordinated pattern or a coincidental "
           "cluster of unrelated cases?")


def show(title, questions):
    """Print a labelled question set, each graded by the real gate."""
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")
    if not questions:
        print("  (none generated)")
        return 0, 0
    good = 0
    for q in questions:
        bad = sq.bad_question(q)
        print(f"  {'✗' if bad else '✓'} {q}" + (f"\n      └─ {bad}" if bad else ""))
        good += (not bad)
    avg = sum(len(q.split()) for q in questions) // max(1, len(questions))
    print(f"  → {good}/{len(questions)} pass · avg {avg} words")
    return good, len(questions)


def main():
    branch = sys.argv[1] if len(sys.argv) > 1 else "missing-scientists-v14"
    only = None
    if "--person" in sys.argv:
        only = sys.argv[sys.argv.index("--person") + 1]
    mm = MemoryMap()
    print(f"Previewing questions against branch: {branch}  (NO fetching — generators only)")

    tot_good = tot_all = 0

    # 1. the opening leads the director builds from the seeded roster (pure templates, no LLM)
    g, n = show("1 · ENTITY LEADS (one per roster person — template, no LLM)",
                [f"What happened to {e}? Documented status and cause." for e in ROSTER[:5]])
    tot_good += g; tot_all += n

    # 2. the case plan's questions (one LLM call)
    plan = build_case_plan(SUBJECT)
    g, n = show("2 · CASE-PLAN LEADS (base rates, anomalies, hypothesis tests)",
                targeted_questions(plan, max_q=8))
    tot_good += g; tot_all += n

    # 3. the per-person interrogation bank — THE evidence-fed generator
    people = [only] if only else ROSTER[:3]
    for person in people:
        ev = I.evidence_for(SUBJECT, person, branch_id=branch, mm=mm)
        g, n = show(f"3 · QUESTION BANK — {person}  ({len(ev)} findings fed in)",
                    I.question_bank(SUBJECT, person, n=6, branch_id=branch, mm=mm))
        tot_good += g; tot_all += n

    # 4. the Mind's wave-2 — reads the map, asks what's next
    try:
        from seeker.mind.mind import generate_next_questions
        w2 = generate_next_questions(SUBJECT, branch_id=branch, n=6)
        g, n = show("4 · MIND WAVE-2 (reads the whole map, asks the frontier questions)",
                    [r.get("q", "") for r in w2 if r.get("q")])
        tot_good += g; tot_all += n
    except Exception as e:
        print(f"\n  (wave-2 unavailable: {e})")

    # 5. connection-driven follow-ups — a link should raise its own next questions
    try:
        from seeker import connections as _conn
        conns = _conn.find_connections(SUBJECT, branch_id=branch, mm=mm)
        g, n = show("5 · FROM CONNECTIONS (each link/non-link raises a follow-up)",
                    I.questions_from_connections(SUBJECT, conns, n=6))
        tot_good += g; tot_all += n
    except Exception as e:
        print(f"\n  (connection questions unavailable: {e})")

    print(f"\n{'=' * 70}\nTOTAL: {tot_good}/{tot_all} questions pass the gate "
          f"({tot_good * 100 // max(1, tot_all)}%)\n{'=' * 70}")


if __name__ == "__main__":
    main()
