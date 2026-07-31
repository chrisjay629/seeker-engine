"""A/B: do the NEW questions actually retrieve better evidence than the OLD ones?

Vera's test (2026-07-27). The whole session moved question quality from 0% to 90% — but that score
is against a gate WE wrote. Nobody has shown a better-phrased question returns better EVIDENCE. This
drives MATCHED PAIRS (same subject, old phrasing vs new) through the SAME fetcher with the SAME
budget, into a scratch branch, and prints what each actually brought back.

If the new questions don't win, we've been polishing a proxy metric all night and need to know it.

  .venv/bin/python tools/ab_questions.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from seeker.hunt import seeker_agent as sa   # noqa: E402

BRANCH = "ab-question-test"
MAX_PAGES = 2          # identical budget for both arms

# MATCHED PAIRS — same investigative target, only the phrasing differs.
# OLD = verbatim from v14's question ledger (what the app actually asked).
# NEW = what the evidence-fed generators produce now (verbatim from tools/preview_questions.py).
PAIRS = [
    ("What are the most detailed available primary source documents reporting the status and "
     "disappearance of Anthony Chavez, Steven Garcia, Jason Thomas, and Frank Maiwald, and what, "
     "specifically, do they establish about each individual's fate?",
     "Who last saw Anthony Chavez at his home in May 2025?"),

    ("What primary-source documents (police reports, medical examiner statements, direct "
     "communications) explicitly confirm the verified status (missing, deceased, or status "
     "unconfirmed) and the documented circumstances for Monica Jacinto Reza?",
     "Who last saw Monica Jacinto Reza on June 22, 2025?"),

    ("Have any of the deceased individuals in this list (Loureiro, Grillmair, etc.) been officially "
     "ruled to have died by homicide according to documented primary sources, and what are those "
     "documents?",
     "Who found Carl Grillmair's body on February 16, 2026?"),

    ("Is there any public or private correspondence (emails, memos, recordings) indicating "
     "professional, social, or operational connections among more than two of the individuals, as "
     "established by original source or subpoenaed material?",
     "Which rocket materials project listed both Reza and McCasland as team members?"),

    ("Do any of the surviving colleagues or family members of the named individuals—cited by name, "
     "date, and recording—provide firsthand evidence supporting or opposing the idea of a "
     "coordinated pattern or shared cause of disappearance/death?",
     "What did Amy Eskridge's text messages one month before death say?"),
]


def drive(q, tag):
    """Run ONE question through the real web lane. Returns (n_findings, elapsed, sample_claims)."""
    t0 = time.monotonic()
    try:
        findings = sa.seek(q, branch_id=BRANCH, max_pages=MAX_PAGES)
    except Exception as e:
        print(f"    [{tag}] ERROR {type(e).__name__}: {str(e)[:80]}")
        return 0, 0.0, []
    dt = time.monotonic() - t0
    claims = [(getattr(f, "claim", "") or "") for f in findings]
    return len(findings), dt, claims


def main():
    print(f"A/B on {len(PAIRS)} matched pairs · same fetcher · max_pages={MAX_PAGES} · branch={BRANCH}\n")
    tot_old = tot_new = 0
    for i, (old, new) in enumerate(PAIRS, 1):
        print("=" * 74)
        print(f"PAIR {i}")
        print(f"  OLD ({len(old.split())}w): {old[:95]}...")
        print(f"  NEW ({len(new.split())}w): {new}")
        n_old, t_old, c_old = drive(old, "old")
        n_new, t_new, c_new = drive(new, "new")
        tot_old += n_old
        tot_new += n_new
        print(f"\n  → OLD returned {n_old} findings ({t_old:.0f}s)   |   NEW returned {n_new} findings ({t_new:.0f}s)")
        print("  OLD sample:")
        for c in c_old[:2]:
            print(f"    · {c[:105]}")
        if not c_old:
            print("    · (nothing)")
        print("  NEW sample:")
        for c in c_new[:2]:
            print(f"    · {c[:105]}")
        if not c_new:
            print("    · (nothing)")
        print()

    print("=" * 74)
    print(f"TOTAL findings — OLD: {tot_old}   NEW: {tot_new}")
    if tot_new > tot_old:
        print(f"NEW wins on volume (+{tot_new - tot_old}). Read the samples for whether they ANSWER the question.")
    elif tot_new < tot_old:
        print(f"OLD returned more ({tot_old - tot_new} more). Volume is not quality — read the samples.")
    else:
        print("Tie on volume — read the samples.")
    print("Judge on the SAMPLES: which set actually answers what was asked?")


if __name__ == "__main__":
    main()
