"""Case files (Chris's design, 2026-07-30) — one container per person, then triage inside it.

HIS FRAMING, which is the whole architecture: "When it compiles all the evidence about one
individual to one node, it doesn't mean that all that information needs to be used when producing
the map. It just means that all the information about that person is in that node. Now we scan
through it to see what's useful and what's not, then give a summarized version of what's useful."

That distinction is what makes this safe. The case file is a CONTAINER, not a summary — every
finding about a person is in it, losslessly. Triage happens INSIDE the container and records a
verdict per finding. Only the useful part flows onward. Nothing is destroyed by compression, which
is precisely how the v19 report lost "investigators used Tesla telemetry to track LeBlanc's
movements": a summary replaced the evidence instead of pointing at it.

WHY IT ALSO SOLVES THE COST PROBLEM. Reviewing 677 loose findings one at a time is expensive.
Reviewing 13 case files is one call each — so EVERY finding can be judged at full depth, with no
relevance ceiling deciding which ones deserve a look.

AND THE PART NOBODY ASKED FOR, which turned out to matter most. Clustering by person leaves a
remainder: findings that attach to no one on the roster. On v19 that pile is 347 of 677 — over half
the corpus — and it is where the contamination lives: a Tennessee heroin case that matched SULLIVAN
COUNTY (not Matthew James Sullivan), an arrest of NOE Garcia, Oklahoma prosecutors, a Florida
tax-fraud task force. Sorting by entity isolates that automatically. The orphan pile is triaged too,
never ignored, because "belongs to nobody" is exactly the shape of both junk AND genuine
cross-cutting evidence, and only reading it tells you which.

VERDICTS are recorded per finding, so "reviewed" is a fact we can point at rather than a claim:
    keep      — evidence about this person, relevant to the case
    context   — true and about them, but background rather than case evidence
    reject    — a different person, a different case, or unrelated to the investigation
A rejected finding is NEVER deleted. It keeps its node and its verdict, so a wrong call is
visible and reversible (Vera). Deletion would make the triage unfalsifiable.
"""
from __future__ import annotations

from . import synthesis as _synthesis
from .entity_profiles import _entity_keys
from .memory.gap_detector import _reason_json

_VERDICTS = ("keep", "context", "reject")


def build_case_files(entities: list, *, branch_id: str = "main", mm=None) -> dict:
    """{name: [finding, ...]} plus an "_unassigned" bucket. LOSSLESS — every finding on the branch
    lands somewhere, and the counts add up to the whole map.

    A finding mentioning two people is filed under BOTH: shared evidence is how connections are
    found, and forcing it into one file would hide it from the other person's review."""
    findings = _synthesis.all_findings(branch_id, mm)
    names = [str(e).strip() for e in (entities or []) if str(e).strip()]
    files: dict = {n: [] for n in names}
    files["_unassigned"] = []
    for f in findings:
        low = (f.get("claim") or "").lower()
        owners = [n for n in names if any(k in low for k in _entity_keys(n))]
        if owners:
            for n in owners:
                files[n].append(f)
        else:
            files["_unassigned"].append(f)
    return files


_TRIAGE_PROMPT = (
    "You are triaging the evidence file for ONE SUBJECT in an investigation. For EVERY numbered "
    "finding, decide what it is:\n"
    "  keep    — evidence about THIS subject, relevant to what happened to them\n"
    "  context — true and about them, but background (career history, publications, family "
    "detail) rather than case evidence\n"
    "  reject  — a DIFFERENT person who shares the name, a different case entirely, or material "
    "with no bearing on this investigation\n\n"
    "REJECT IS THE IMPORTANT ONE and it is usually a name collision. A finding can mention the "
    "subject's surname and still be about someone else — a county, a company, an unrelated "
    "defendant. If the finding's subject does not match who this person is, reject it and say so.\n"
    "Do NOT reject a finding merely for being thin, uncorroborated or unflattering; only for being "
    "about something else. An unverified claim about the RIGHT person is 'keep' — its tier already "
    "records the doubt.\n"
    'Return STRICT JSON: {"verdicts": [{"n": 1, "verdict": "keep", "why": "<=12 words"}, ...]} '
    "with one entry for EVERY finding number given."
)


def triage_file(subject_name: str, findings: list, *, who: str = "", max_batch: int = 120) -> list:
    """Judge every finding in one person's file. Returns the findings with `verdict` and `why` set.

    Batched so a large file still gets full coverage — an 80-finding file is one or two calls, and
    every finding is judged. Fail-open: on any error everything is marked 'keep' with the reason
    recorded, because an unreviewed finding must not silently become a rejected one."""
    out = []
    for start in range(0, len(findings), max_batch):
        batch = findings[start:start + max_batch]
        listing = "\n".join(f"{i+1}. {f.get('claim','')[:260]}" for i, f in enumerate(batch))
        try:
            data = _reason_json(
                _TRIAGE_PROMPT
                + f"\n\nSUBJECT: {subject_name}"
                + (f"\nWHO THEY ARE: {who}" if who else "")
                + f"\n\nFINDINGS:\n{listing}\n") or {}
            byn = {int(v.get("n", 0)): v for v in (data.get("verdicts") or [])
                   if str(v.get("n", "")).strip().isdigit()}
        except Exception as e:
            byn = {}
            err = repr(e)[:60]
        for i, f in enumerate(batch):
            v = byn.get(i + 1) or {}
            rec = dict(f)
            verdict = str(v.get("verdict", "")).lower().strip()
            rec["verdict"] = verdict if verdict in _VERDICTS else "keep"
            rec["why"] = str(v.get("why", "") or ("unreviewed — kept by default"
                                                  if not v else ""))[:90]
            out.append(rec)
    return out


def triage_all(entities: list, *, branch_id: str = "main", mm=None,
               cards: dict | None = None, include_unassigned: bool = True) -> dict:
    """Build every case file and triage all of them. Returns
    {files: {name: [finding+verdict]}, stats: {...}}.

    `cards` (identity cards) are passed into each triage as WHO THIS PERSON IS — the single most
    useful input for catching a namesake, since "reject: this is a Tennessee county, not Matthew
    James Sullivan" needs to know who Sullivan actually was."""
    from . import identity as _identity
    files = build_case_files(entities, branch_id=branch_id, mm=mm)
    triaged, stats = {}, {}
    for name, fs in files.items():
        if name == "_unassigned" and not include_unassigned:
            continue
        if not fs:
            triaged[name] = []
            continue
        who = ""
        if cards and name in cards:
            who = _identity.disambiguator(cards[name]) or ""
        subject = ("findings that mention nobody on the roster — decide whether each is "
                   "cross-cutting case evidence or unrelated material"
                   if name == "_unassigned" else name)
        rows = triage_file(subject, fs, who=who)
        triaged[name] = rows
        stats[name] = {v: sum(1 for r in rows if r["verdict"] == v) for v in _VERDICTS}
        stats[name]["total"] = len(rows)
    return {"files": triaged, "stats": stats}


def useful(triaged: dict, *, include_context: bool = False) -> list:
    """The findings that survived triage — what the map should actually be built from."""
    ok = {"keep"} | ({"context"} if include_context else set())
    seen, out = set(), []
    for rows in (triaged.get("files") or {}).values():
        for r in rows:
            if r.get("verdict") in ok and r.get("id") not in seen:
                seen.add(r.get("id"))
                out.append(r)
    return out


def format_triage(res: dict) -> str:
    stats = res.get("stats") or {}
    lines = ["— CASE FILES (every finding reviewed, verdict recorded) —",
             f"  {'subject':26s} {'total':>6} {'keep':>6} {'context':>8} {'reject':>7}"]
    tot = {"total": 0, "keep": 0, "context": 0, "reject": 0}
    for name, s in sorted(stats.items(), key=lambda kv: -kv[1]["total"]):
        lines.append(f"  {name[:26]:26s} {s['total']:>6} {s['keep']:>6} "
                     f"{s['context']:>8} {s['reject']:>7}")
        for k in tot:
            tot[k] += s.get(k, 0)
    lines.append(f"  {'ALL':26s} {tot['total']:>6} {tot['keep']:>6} "
                 f"{tot['context']:>8} {tot['reject']:>7}")
    return "\n".join(lines)
