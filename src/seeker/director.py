"""Lead Investigator (Director) — the meta-organ that works a CASE, not a search (brief 29).

Codifies the Investigation Doctrine (Blackstone's ABC + Heuer/Pherson ACH + Bellingcat OSINT):
decompose the case into a diligence plan, drive the existing organs DEEP against every open item,
compete the hypotheses by seeking DISCONFIRMING evidence (ACH), chase the cracks, track coverage,
and only conclude when the case is worked — then write it up. Reuses every organ we built; the new
intelligence here is the case-plan decomposer and the ACH engine.

Guardrails (council): the plan MUST include the mundane/base-rate hypothesis (Noor); a hard lead
ceiling keeps it diligent, not infinite (Marcus/Noor); investigate evidence & theories, never accuse
a named person (Ghost).
"""
from __future__ import annotations

from .memory.memory_map import MemoryMap
from .memory.gap_detector import _reason_json


def build_case_plan(subject: str) -> dict:
    """Decompose a case into the diligence checklist a top-tier investigator would work.
    Returns {claims_to_verify, hypotheses, key_assumptions, entities, base_rate_questions, anomalies}."""
    prompt = (
        "You are the lead investigator opening a CASE (not running a search). Decompose the subject "
        "below into a diligence plan a top-tier investigator (detective + intelligence analyst + OSINT "
        "journalist) would work. Hard rules: (a) the hypotheses MUST include the MUNDANE / ordinary / "
        "coincidence explanation, not only dramatic ones; (b) include at least one BASE-RATE question "
        "(what is normal / the denominator); (c) name the KEY ASSUMPTIONS to test; (d) investigate "
        "evidence and theories only — never presume a named person's guilt.\n\n"
        f"SUBJECT: {subject}\n\n"
        "EVERY question/claim you write must be SHORT (under 12 words), ONE question, and name "
        "something specific. Never ask whether a document exists — ask what happened. "
        "GOOD: 'How many scientists vanish in New Mexico yearly?' BAD: 'What is the annual rate of "
        "missing/unaccounted for scientists in the relevant region globally and per demographic?'\n\n"
        'Return STRICT JSON: {"claims_to_verify": ["specific checkable claims"], '
        '"hypotheses": ["competing explanations incl. the mundane one"], '
        '"key_assumptions": ["what we are taking for granted"], '
        '"entities": ["people/orgs/events to cross-reference"], '
        '"base_rate_questions": ["what is the normal rate / denominator"], '
        '"anomalies": ["details that do not fit / worth chasing"]}')
    data = _reason_json(prompt)
    if not isinstance(data, dict):
        return {}
    keys = ("claims_to_verify", "hypotheses", "key_assumptions", "entities",
            "base_rate_questions", "anomalies")
    return {k: [str(x).strip() for x in (data.get(k) or []) if str(x).strip()] for k in keys}


def targeted_questions(plan: dict, max_q: int = 12) -> list:
    """Turn the plan into concrete investigative questions to hunt — prioritized: base rates &
    anomalies first (where diligence pays), then hypothesis-tests, then claim verification."""
    qs = []
    for b in plan.get("base_rate_questions", []):
        qs.append(b)
    for a in plan.get("anomalies", []):
        qs.append(str(a))          # the anomaly IS the question — no scaffolding wrapper
    for h in plan.get("hypotheses", []):
        qs.append(f"What disproves this: {h}")
    for c in plan.get("claims_to_verify", []):
        qs.append(f"Who first reported this: {c}")
    # de-dup, cap
    seen, out = set(), []
    for q in qs:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out[:max_q]


def harvest_entities(subject: str, *, branch_id: str = "main", recency_years: int | None = None,
                     num_results: int = 4, seed_entities: list | None = None) -> list:
    """Brief 29 — front-load the SPOKEN-WORD organs as an ENTITY-MAP, before the web sweep.

    YouTube + podcasts surface checkable leads (people, orgs, patents, programs, places, dates) the
    web pass would otherwise never chase — proven on Reza (Mondaloy, Gen. McCasland). We harvest ONLY
    the checkable NOUNS and DISCARD the hosts' theories/narrative: the anchoring risk is the framing,
    not the entities. The web/primary hunt then verifies these independently. Returns a deduped list
    of entity strings. Fail-open to []. (Vera: nouns travel forward, conclusions do not.)"""
    from .recon import youtube, podcast
    # the two spoken-word lanes are INDEPENDENT — run them concurrently, not one-then-the-other
    # (measured: 110s serial -> ~59s, the slower lane; task #20 lever 1). Each lane fails open to [].
    def _yt():
        try:
            return youtube.gather(subject, num_results=num_results, branch_id=branch_id,
                                  recency_years=recency_years, entities=seed_entities)[1] or []
        except Exception:
            return []
    def _pod():
        try:
            # pass the KNOWN roster: searching a person's name finds the show dedicated to the case,
            # which genre terms never surface (verified 2026-07-21 — 'Neil McCasland' -> "Missing
            # Scientists", the show that names the whole roster in its description).
            return podcast.gather(subject, num_results=num_results, branch_id=branch_id,
                                  recency_years=recency_years, entities=seed_entities)[1] or []
        except Exception:
            return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_yt, f_pod = ex.submit(_yt), ex.submit(_pod)
        transcripts = (f_yt.result() or []) + (f_pod.result() or [])
    if not transcripts:
        return []
    blob = "\n\n".join((t.get("title", "") + ": " + t.get("text", "")[:2500]) for t in transcripts)[:9000]
    prompt = (
        "Below are podcast/video transcripts about a case. Extract ONLY concrete, CHECKABLE entities "
        "a fact-checker could look up independently — named people, organizations, patents/programs/"
        "products, places, documents, and specific dates. Do NOT include the hosts' theories, "
        "speculation, conclusions, or narrative framing — nouns only, not claims. If a name is "
        "spelled several ways, list each spelling.\n\n"
        f"SUBJECT: {subject}\n\nTRANSCRIPTS:\n{blob}\n\n"
        'Return STRICT JSON: {"entities": ["specific checkable noun/name/date"]}')
    data = _reason_json(prompt)
    ents = [str(e).strip() for e in (data.get("entities", []) if isinstance(data, dict) else [])
            if str(e).strip()]
    seen, out = set(), []
    for e in ents:
        if e.lower() not in seen:
            seen.add(e.lower())
            out.append(e)
    return out[:20]


def _names_from(text_blob: str) -> set:
    """Lowercase multi-word proper-name tokens (>=2 capitalised words) from a text blob — a cheap
    way to compare entity rosters without an LLM. 'Monica Jacinto Reza' -> {'monica jacinto reza'}."""
    from .entity_resolution import proper_names   # one canonical extractor (no drift)
    return {n.lower() for n in proper_names(text_blob)}


def check_completeness(subject: str, found_entities: list, *, branch_id: str = "main",
                       recency_years: int | None = None) -> dict:
    """Completeness gate (the fix for the correctness-vs-completeness failure). For a roster/cluster
    case, fetch the CANONICAL enumeration and diff it against what we actually investigated — flag
    names present in authoritative sources but MISSING from our roster.

    Grounded, fail-open: the 'canonical list' comes from real fetched findings (never invented);
    flagged names are 'possibly missing, unverified' — surfaced as open threads, not asserted facts
    (Vera/Ghost). Returns {canonical: [...], missing: [...]}. Empty on any error or non-roster case."""
    from .hunt import seeker_agent
    try:
        found_norm = {str(e).strip().lower() for e in (found_entities or []) if str(e).strip()}
        # Search-native ENUMERATION queries (task #34) — the old single instruction-shaped query
        # ('Complete authoritative list of ALL named individuals in: X') retrieved poorly; these are
        # phrased how a person actually searches for a full roster, and we union several.
        from . import discovery as _disc
        hits = []
        for _q in _disc.enumeration_queries(subject)[:3]:
            try:
                hits += seeker_agent.seek(_q, branch_id=branch_id, max_pages=2,
                                          recency_years=recency_years)
            except Exception:
                continue
        blob = " ".join(getattr(f, "claim", "") for f in hits)
        canonical = _names_from(blob)
        # a name is 'missing' if the canonical source names it and none of our entities contain it
        missing = []
        for c in canonical:
            if not any(c in fe or fe in c for fe in found_norm):
                missing.append(c.title())
        return {"canonical": sorted(canonical), "missing": sorted(set(missing))[:20]}
    except Exception:
        return {"canonical": [], "missing": []}



def _organ_failed(name: str, exc, *, subject: str = "", branch_id: str = "main") -> None:
    """Record an organ that did not fire, to the public failure wall.

    Every optional organ in this run is wrapped in `except: print("[x skipped]")`, so a failure
    scrolled past in a log and was gone. That made "which organs are firing?" unanswerable after
    the fact — the question Chris had to ask by hand. A skipped organ is now a logged event with
    its reason, so the next run can be checked instead of assumed. Never raises: a failure in the
    failure logger must not take down the investigation it is reporting on."""
    try:
        from . import failure_log as _fl
        _fl.log_failure(question=subject or "(investigation)", path=f"organ:{name}",
                        where_failed=name, reasoning_trail=[repr(exc)[:300]],
                        correction="organ skipped; run continued without it",
                        status="degraded", branch_id=branch_id)
    except Exception:
        pass

def ach_score(subject: str, hypotheses: list, *, branch_id: str = "main",
              mm: MemoryMap | None = None, top_k: int | None = None) -> list:
    """Analysis of Competing Hypotheses (Heuer): for each hypothesis, weigh the DISCONFIRMING evidence
    on the map; the hypothesis that SURVIVES disconfirmation is the strongest — NOT the one with the
    most confirming evidence. Returns [{hypothesis, verdict, disconfirming, why}] grounded in findings."""
    if not hypotheses:
        return []
    mm = mm or MemoryMap()
    from . import synthesis as _syn
    buckets = _syn.gather_findings(subject, branch_id=branch_id, top_k=top_k, mm=mm)
    rows = []
    for label in ("well-supported", "contested", "unverified", "disproven"):
        for r in buckets.get(label, []):
            rows.append(f"[{label}] {r['claim']}")
    blob = "\n".join(rows) or "(no findings)"   # ACH weighs hypotheses against ALL evidence
    hlist = "\n".join(f"- {h}" for h in hypotheses)
    prompt = (
        "Run ANALYSIS OF COMPETING HYPOTHESES (Heuer). For EACH hypothesis below, using ONLY the "
        "findings, list the evidence that DISCONFIRMS it, and judge whether it SURVIVES, is WEAKENED, "
        "or is REFUTED by that disconfirming evidence. The strongest hypothesis is the one with the "
        "LEAST disconfirming evidence — do NOT reward 'most confirming evidence'. Ground everything in "
        "the findings; no outside knowledge; accuse no named person.\n\n"
        f"SUBJECT: {subject}\n\nHYPOTHESES:\n{hlist}\n\nFINDINGS:\n{blob}\n\n"
        'Return STRICT JSON: {"ach": [{"hypothesis": "...", "verdict": "survives|weakened|refuted", '
        '"disconfirming": ["..."], "why": "one sentence"}]}')
    data = _reason_json(prompt)
    out = []
    for r in (data.get("ach", []) if isinstance(data, dict) else []):
        if not isinstance(r, dict):
            continue
        v = str(r.get("verdict", "")).strip().lower()
        if v not in ("survives", "weakened", "refuted"):
            v = "weakened"
        out.append({"hypothesis": str(r.get("hypothesis", "")).strip(), "verdict": v,
                    "disconfirming": [str(x).strip() for x in (r.get("disconfirming") or [])][:5],
                    "why": str(r.get("why", "")).strip()})
    return out


def suggest_next_questions(subject: str, coverage: list, open_threads: list, *,
                           branch_id: str = "main", mm=None, n: int = 8) -> list:
    """WHAT WOULD YOU LIKE TO RESEARCH NEXT? — a pick-list for the human (Gambit, 2026-07-28).

    Seeker chases its own follow-ups automatically, but it never ASKED the owner which thread to
    pull. A run ends with 40+ leads worked and a dozen threads still open, and the person who knows
    what matters gets no say. This offers the genuine next questions, ranked, so the next run can be
    aimed rather than repeated.

    Assembly, not a new organ (Zara): the open-threads organ already isolates what stayed unresolved,
    and follow_ups already turns a rich answer into its next question. This picks from BOTH — what is
    UNRESOLVED (load-bearing, Noor: not merely what is easy to ask) and what a strong answer just
    opened — dedupes, and runs the same question gate everything else passes (Vera). Generation only:
    no fetching, so it costs pennies. Fail-open to []."""
    from . import interrogate as _intg_nq
    from . import search_queries as _sq_nq
    out, seen = [], set()

    # 1. unresolved threads first — these are the ones that would actually move the case
    for th in (open_threads or [])[:10]:
        s = " ".join(str(th).split())
        if s and not _sq_nq.bad_question(s) and s.lower() not in seen:
            seen.add(s.lower())
            out.append({"q": s, "why": "still unresolved after this run"})

    # 2. then doors the richest answers opened but we did not walk through
    rich = sorted([c for c in (coverage or []) if c.get("covered") and c.get("claims")],
                  key=lambda c: -int(c.get("findings", 0)))[:4]
    for row in rich:
        for q in _intg_nq.follow_ups(subject, row["lead"], row.get("claims") or [], n=2,
                                     already_asked=seen):
            s = " ".join(str(q).split())
            if s and not _sq_nq.bad_question(s) and s.lower() not in seen:
                seen.add(s.lower())
                out.append({"q": s, "why": f"raised by a lead that returned {row.get('findings',0)} findings"})
    return out[:n]


def _open_threads(subject: str, plan: dict, coverage: list, ach: list, ledger: list,
                  mm: "MemoryMap", branch_id: str) -> list:
    """Surface GENUINE unresolved questions, not just leads that returned nothing.

    A lead can be fully WORKED yet leave the question OPEN — that was the bug (0 threads on an
    unsolved case). Real open threads come from: (a) leads that found nothing, (b) hypotheses still
    LIVE after ACH (survives/weakened, i.e. not refuted), (c) claims the ledger left unproven /
    contested / hearsay, (d) case-plan anomalies, and (e) internal CONTRADICTIONS in the evidence
    (e.g. a name or date that sources disagree on). Grounded, deduped, capped. Fail-open."""
    threads = []
    for c in coverage:
        if not c.get("covered"):
            threads.append(f"No evidence found for: {c['lead']}")
    for a in (ach or []):
        if str(a.get("verdict", "")).lower() in ("survives", "weakened"):
            threads.append(f"Still live — not resolved: {a.get('hypothesis', '')}")
    for cl in (ledger or []):
        if str(cl.get("verdict", "")).lower() in ("unproven", "contested", "hearsay"):
            threads.append(f"Unresolved claim ({cl.get('verdict')}): {cl.get('claim', '')}")
    for an in (plan.get("anomalies") or [])[:4]:
        threads.append(f"Anomaly not put to rest: {an}")

    # (e) LLM pass — find CONTRADICTIONS the evidence itself contains (the name/date-conflict class
    # the binary generator missed). Grounded only in gathered findings; fail-open to the heuristics.
    try:
        # the contradiction hunter reads EVERY finding, not a relevance slice — a contradiction
        # between two claims is exactly the kind of thing that hides outside a top-k window
        from . import synthesis as _syn_ct   # local: _open_threads has no module-level _syn
        hits = [{"text": f["claim"]} for f in _syn_ct.all_findings(branch_id, mm)]
        corpus = "\n".join(f"- {h.get('text', '')[:180]}" for h in hits)[:60000]
        if corpus:
            prompt = (
                "Below are findings gathered in an investigation. List ONLY genuine UNRESOLVED "
                "questions and internal CONTRADICTIONS the findings themselves reveal — conflicting "
                "names/dates/numbers, claims that appear but were never confirmed, gaps a diligent "
                "investigator would still chase. Do NOT invent anything not present. Do NOT restate "
                "settled facts. If nothing is genuinely unresolved, return an empty list.\n\n"
                f"SUBJECT: {subject}\n\nFINDINGS:\n{corpus}\n\n"
                'Return STRICT JSON: {"open": ["specific unresolved question or contradiction"]}')
            data = _reason_json(prompt)
            if isinstance(data, dict):
                for o in (data.get("open") or [])[:8]:
                    if str(o).strip():
                        threads.append(str(o).strip())
    except Exception:
        pass

    seen, out = set(), []
    for t in threads:
        k = t.strip().lower()
        if t.strip() and k not in seen:
            seen.add(k)
            out.append(t.strip())
    return out[:15]


def _drive_lead(q: str, *, branch_id: str, per_lead_pages: int, recency_years, mm) -> dict:
    """Work ONE lead: web/primary verification hunt + active counter-evidence. Spoken-word lanes
    are OFF here (harvest + seed already ran them). Returns a coverage row. Safe to run in parallel —
    hunt() uses its own MemoryMap and the rate governor caps per-provider concurrency."""
    from .hunt.hunt import hunt
    from .hunt import query_expansion
    from .memory.consolidation import upsert_findings_consolidated
    res = hunt(q, branch_id=branch_id, max_pages=per_lead_pages, recency_years=recency_years,
               with_youtube=False, with_podcast=False)
    n = len(res.findings)
    try:
        counter = query_expansion.seek_counter_evidence(q, mm, branch_id=branch_id,
                                                        recency_years=recency_years)
        if counter:
            upsert_findings_consolidated(mm, counter)
            n += len(counter)
    except Exception:
        pass
    # claims travel back with the row so the FOLLOW-UP HOP can read what this question actually
    # answered (additive key — only .get("covered") is consumed elsewhere).
    try:
        _claims = [(getattr(f, "claim", "") or "") for f in (res.findings or [])][:10]
    except Exception:
        _claims = []
    return {"lead": q, "findings": n, "covered": n > 0, "claims": _claims}


def _drive_leads(leads: list, *, parallel: bool, branch_id: str, per_lead_pages: int,
                 recency_years, mm) -> list:
    """Drive all leads and return coverage rows IN LEAD ORDER (task #18).

    Leads are independent web/primary verifications, so run them CONCURRENTLY when parallel=True:
    the work is network-I/O-bound (threads give real concurrency despite the GIL), and the rate
    governor caps per-provider concurrency so parallel leads queue safely instead of self-throttling
    — ~3-5x faster wall-clock at the same total cost. executor.map preserves input order. A single
    lead or parallel=False takes the simple serial path."""
    from . import watchdog
    def _lead(q):
        r = _drive_lead(q, branch_id=branch_id, per_lead_pages=per_lead_pages,
                        recency_years=recency_years, mm=mm)
        watchdog.beat("leads")             # each completed lead is progress — keeps the backstop happy
        return r
    if parallel and len(leads) > 1:
        from concurrent.futures import ThreadPoolExecutor
        workers = min(len(leads), 8)   # bounded; the rate governor is the real provider-side cap
        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(_lead, leads))
    return [_lead(q) for q in leads]


def _contribution_ledger(subject, branch_id, mm, *, ach, ledger, open_threads, conclusion,
                         entities, conns=None, disag=None, report=None, top_corr=None,
                         pclaims=None) -> list:
    """Per-organ CONTRIBUTION — makes 'called vs contributed' visible in the OUTPUT (not just a test).
    Every flagship organ reports what it actually added: 0 = DEAD (fired but produced nothing);
    not-wired = ABSENT. A hollow organ (e.g. citation-graph 2/800) now shows in the data Gambit reads,
    so nobody has to trust a green checkmark. Born 2026-07-18 from the wiring audit."""
    try:
        mix = mm.organ_mix(subject, branch_id=branch_id)
    except Exception:
        mix = {}
    rows = []
    # Does this case even HAVE an academic angle? The citation-graph (OpenAlex) only chases real
    # published PAPERS. On a news/missing-persons case there are none to chase, so 0 findings is
    # N/A (right tool, wrong case) — NOT a broken organ. We proved the engine resolves real paper
    # titles fine, and that author-name seeding false-attributes (scholar.py note). So we distinguish:
    # 0 academic sources in the whole case  -> N/A ;  papers present but graph empty -> genuine DEAD.
    _academic = int(mix.get("abstract", 0)) + int(mix.get("secondary_review", 0))
    _CITATION_KEYS = {"abstract", "secondary_review"}
    for key, label in [("web", "Web search"), ("primary_source", "Primary sources (H4)"),
                       ("structured_source", "Structured registry"), ("youtube", "YouTube lane"),
                       ("podcast", "Podcast lane"), ("abstract", "Citation-graph (H6)"),
                       ("secondary_review", "Citation-graph review")]:
        n = int(mix.get(key, 0))
        if key in _CITATION_KEYS and _academic == 0:
            st = "N/A (no academic sources in case)"
        else:
            st = "DEAD (0 findings)" if n == 0 else ("weak (barely fired)" if n < 5 else "firing")
        rows.append({"organ": label, "added": f"{n} findings", "status": st})
    for label, n in [("ACH hypotheses", len(ach or [])), ("Claim ledger", len(ledger or [])),
                     ("Open threads", len(open_threads or [])),
                     ("Entity resolution", len(entities or []))]:
        rows.append({"organ": label, "added": f"{n}",
                     "status": "firing" if n else "DEAD (empty)"})
    rows.append({"organ": "Synthesis", "added": "conclusion" if conclusion else "—",
                 "status": "firing" if conclusion else "DEAD (empty)"})
    # newly-wired analysis organs (integration task #27) — report REAL contribution
    nc = len((conns or {}).get("connections", [])) if conns else 0
    nn = len((conns or {}).get("non_connections", [])) if conns else 0
    rows.append({"organ": "Connections Engine", "added": f"{nc} links, {nn} non-links",
                 "status": "firing" if (nc or nn) else "DEAD (no analysis)"})
    dm = (disag or {}).get("map", {}) if disag else {}
    contested = bool(dm.get("contested"))
    rows.append({"organ": "Disagreement map",
                 "added": f"{len(dm.get('sides', []))} sides" if contested else "uncontested",
                 "status": "firing" if dm else "DEAD (empty)"})
    rep = (report or {}).get("report", "") if report else ""
    nt = len((report or {}).get("notable_threads", [])) if report else 0
    rows.append({"organ": "Quill report", "added": f"{len(rep.split())} words, {nt} threads",
                 "status": "firing" if rep else "DEAD (empty)"})
    ntc = len(top_corr or [])
    rows.append({"organ": "Corroboration ranking", "added": f"{ntc} top-corroborated",
                 "status": "firing" if ntc else "DEAD (empty)"})
    # Pattern-Claim Adjudicator (task #28) — how many claimed patterns did it actually work?
    pats = (pclaims or {}).get("claimed_patterns", [])
    npat = len(pats)
    nnotable = sum(1 for p in pats if p.get("verdict") == "unresolved-notable")
    folded = (pclaims or {}).get("folded_count", 0)
    # N/A (honest, not DEAD) when a case simply has NO pattern-claims to adjudicate — same doctrine as
    # the citation-graph: right tool, wrong case is not a failure.
    if pclaims is None:
        pstat = "ABSENT (not wired)"
    elif npat == 0:
        pstat = "N/A (no pattern-claims in case)"
    else:
        pstat = "firing"
    rows.append({"organ": "Pattern-Claim Adjudicator",
                 "added": f"{npat} claims ({nnotable} notable, {folded} folded)", "status": pstat})
    return rows


# Every checkpoint's result, accumulated for the end-of-run CHALLENGER REVIEW. Reset per run so a
# second investigation in the same process does not inherit the first one's critique.
_CHALLENGE_LOG: list = []


class ChallengerAbort(Exception):
    """Raised when the Challenger gate FAILS a checkpoint and abort is armed. Caught by
    run_investigation so the run stops CLEANLY (watchdog disarmed, reason returned) instead of
    burning an hour and hundreds of credits on work we already know is bad."""


def _challenge_checkpoint(name: str, kind: str, samples: list, *, case: str = "",
                          claim: str = "", expected: str = "") -> dict:
    """Run the Challenger at a named point in the run and LEAVE PROOF THAT IT RAN.

    Gambit, 2026-07-28: "I want to know if it is actually hitting or not. I want to find out
    [not] after the full run that it didn't work." So every checkpoint appends a line to
    runs/challenger_live.jsonl the moment it fires — tail that file DURING a run and you can see
    the gate working. An ABSENT line means the gate did not fire, which is itself the finding
    (Noor: a gate that silently no-ops is worse than none).

    If SEEKER_CHALLENGER_ABORT=1 (default) a FAIL raises ChallengerAbort and the run stops HERE.
    The first checkpoint sits BEFORE any fetching, so a bad question set costs seconds, not an
    hour and ~400 credits (Marcus)."""
    import json as _json
    import os as _os2
    import time as _time
    rec = {"at": _time.strftime("%H:%M:%S"), "checkpoint": name, "kind": kind,
           "n_samples": len(samples or []), "verdict": "not-run", "flags": []}
    try:
        from . import challenger as _ch
        res = _ch.challenge(kind, samples, case=case, claim=claim, expected=expected)
        rec["verdict"] = res.get("verdict", "escalate")
        rec["flags"] = [f"{f.get('kind')}: {str(f.get('why'))[:90]}" for f in (res.get("flags") or [])][:6]
        rec["reviewer"] = res.get("reviewer_model", "")
        rec["questions"] = list(res.get("questions") or [])[:6]
        # COURSE CORRECTION (Gambit, 2026-07-28) — when the gate finds drift, it proposes EXTRA
        # questions to pull the run back. Strictly additive: nothing existing is rewritten or
        # dropped, so a wrong correction costs one question while a right one can save the run.
        # Capped run-wide by SEEKER_CORRECTION_LEADS (fetches are dollars — Marcus).
        rec["corrections"] = _ch.course_correction(kind, res, case=case, n=2)
        print(_ch.format_report(res, f"CHALLENGER @ {name}"), flush=True)
    except Exception as e:
        rec["verdict"] = "error"
        rec["flags"] = [f"challenger itself failed: {type(e).__name__}: {str(e)[:80]}"]
        print(f"— CHALLENGER @ {name} — ERROR (gate did not run): {e}", flush=True)
    try:
        _os2.makedirs("runs", exist_ok=True)
        with open("runs/challenger_live.jsonl", "a") as f:
            f.write(_json.dumps(rec) + "\n")
    except Exception:
        pass
    # NO KILL AUTHORITY (2026-07-28, Gambit's correction — the council agreed unanimously). The gate
    # CRITIQUES; it does not stop the investigation. An imperfect judge with abort power is a single
    # point of failure, a false abort costs MORE than it saves (you re-run everything), and worst of
    # all an abort DESTROYS the evidence you would need to judge whether the abort was even right
    # (Noor). A critique you can read afterwards is verifiable; a halt is not. Opt in explicitly with
    # SEEKER_CHALLENGER_ABORT=1 if you ever want a hard stop.
    _CHALLENGE_LOG.append(rec)
    if rec["verdict"] == "fail" and _os2.environ.get("SEEKER_CHALLENGER_ABORT", "0") == "1":
        raise ChallengerAbort(f"{name}: {'; '.join(rec['flags'][:3])}")
    return rec


def run_investigation(subject: str, *, branch_id: str = "main", recency_years: int | None = None,
                      max_leads: int = 10, per_lead_pages: int = 3, parallel: bool = True,
                      seed_entities: list | None = None) -> dict:
    """Public entry — owns the watchdog lifecycle in a try/finally so the stall backstop can NEVER
    outlive the run (audit fix 2026-07-20). Without this, a CAUGHT investigation exception left the
    daemon armed and it os._exit(70)-ed the whole process ~10 min later. The finally disarms it on
    every path. The real work is in _run_investigation_impl."""
    from . import watchdog
    _CHALLENGE_LOG.clear()                 # fresh critique per run
    watchdog.start()                       # always-on stall backstop: dump+abort on 10-min no-progress
    try:
        return _run_investigation_impl(subject, branch_id=branch_id, recency_years=recency_years,
                                       max_leads=max_leads, per_lead_pages=per_lead_pages,
                                       parallel=parallel, seed_entities=seed_entities)
    except ChallengerAbort as e:
        # STOPPED ON PURPOSE — the gate found the output unusable. Return a dossier that says so
        # loudly rather than a half-run masquerading as a result (Vera).
        print(f"\n{'!' * 64}\nRUN ABORTED BY CHALLENGER GATE\n  {e}\n"
              f"  Nothing further was fetched. Fix the flagged issue and re-run.\n"
              f"  (set SEEKER_CHALLENGER_ABORT=0 to warn instead of stopping)\n{'!' * 64}", flush=True)
        return {"aborted_by": "challenger", "reason": str(e), "subject": subject,
                "branch_id": branch_id, "coverage": [], "entities": []}
    finally:
        watchdog.stop()


def _run_investigation_impl(subject: str, *, branch_id: str = "main", recency_years: int | None = None,
                      max_leads: int = 10, per_lead_pages: int = 3, parallel: bool = True,
                      seed_entities: list | None = None) -> dict:
    """Work the case per the doctrine. Seed → plan → drive DEEP against each lead (with active
    counter-evidence) → ACH → claim ledger + synthesis. Bounded by max_leads (the diligence ceiling).
    Returns the full dossier. This drives many hunts — it is deliberately deeper/costlier than a pass.

    seed_entities: a KNOWN roster (people/orgs/cases the caller already knows belong to this case).
    Every one gets its OWN mandatory verification lead — completeness is guaranteed, NOT left to
    discovery. Fixes the failure where discovery surfaced only the prominent names and silently
    dropped the rest. The lead ceiling auto-expands to cover them."""
    import os as _os                       # used from the wave-1 checkpoint onward
    from .hunt.hunt import hunt
    from .hunt import query_expansion
    from .memory.consolidation import upsert_findings_consolidated
    from . import synthesis as _syn
    from . import claim_ledger as _cl
    from . import persistence

    from . import watchdog                  # lifecycle (start/stop) owned by the run_investigation wrapper
    # 0a. QUESTION-FORMER (task #36) — the front door gets the trained questioner. The root question
    # was raw human input, unexamined; v8's topic called a deceased person "missing" and every lead
    # inherited the error. Panel of different models drafts under the Mind's brief-17 doctrine, a
    # grounded fact-check anchors each person's fate, the judge merges and LISTS its corrections.
    # Fail-open (question == raw topic); off-switch SEEKER_FORM_QUESTION=0. The RAW topic is preserved
    # in the dossier for transparency.
    raw_topic = subject
    from . import question_former as _qf
    _raw_topic = subject          # what the caller actually asked, BEFORE question-forming
    formed = _qf.form_question(subject, entities=seed_entities)
    subject = formed.get("question") or subject
    # CASE ANCHOR — distinctive case terms, computed ONCE from the formed question and shared by the
    # structured-registry lane (turns a bare name into a gov-searchable topic query) and the depth
    # equalizer (namesake disambiguation). Set the run-scoped anchor so seek_structured sees it
    # without threading through 5 signatures.
    import re as _re
    _stop = {"the","and","for","that","with","from","this","case","each","named","individual",
             "verified","status","documented","cause","outcome","genuine","coordinated","pattern",
             "coincidental","cluster","unrelated","cases","primary","authoritative","sources","are",
             "following","individuals","what","which","where","when","their","there","these","those",
             "establish","determine","report","reporting","evidence","specified","respectively"}
    # SUBTRACT THE ROSTER (2026-07-27 bug): the question-former now names every person in the formed
    # question, so raw word-extraction produced 'following individuals william neil mccasland mon' —
    # an anchor made of OTHER PEOPLE'S NAMES. Cold-case probes for Sullivan/Maiwald/LeBlanc then got
    # McCasland appended and searched for the wrong person, sending the equalizer's budget to the
    # LOUDEST case: the exact inversion of what it exists to do.
    _name_words = {w.lower() for n in (seed_entities or []) for w in str(n).split() if len(w) > 3}
    # STRIP PER-PERSON DETAIL, not just names (2026-07-28). v18: the question-former annotates each
    # person with their own facts — "William Neil McCasland (publicly reported missing in Albuquerque,
    # New Mexico...)" — so the anchor became 'publicly reported missing albuquerque mexico'. Every
    # anchored probe then got "in Albuquerque" stapled on, and Seeker asked how Nuno Loureiro died in
    # Albuquerque when he was shot in Brookline, Massachusetts. Five leads returned 0 that way.
    # Anything inside the per-person parentheses belongs to ONE person and must never become
    # case-wide context. Same bug class as the roster-name leak — fixed for the class this time.
    _parenthetical = " ".join(_re.findall(r"\(([^)]*)\)", subject)).lower()
    _person_detail = {w for w in _re.findall(r"[A-Za-z]{4,}", _parenthetical)}
    # Built from the RAW TOPIC, not the formed question (2026-07-28). The formed question is a long
    # procedural sentence with per-person annotations; mining it for "case identity" yields either a
    # person's city ('albuquerque') or filler ('fully independently known information'). The raw topic
    # is what the human actually asked — short and case-descriptive — so it distils to the terms that
    # genuinely identify the case ('missing scientists').
    _case_anchor = " ".join(dict.fromkeys(
        w for w in _re.findall(r"[A-Za-z]{4,}", _raw_topic.lower())
        if w not in _stop and w not in _name_words and w not in _person_detail))[:48]
    try:
        from .hunt import seeker_agent as _sa_anchor
        _sa_anchor.set_case_anchor(_case_anchor)
    except Exception:
        pass
    persistence.register(branch_id, subject, "Lead-Investigator diligent case")
    mm = MemoryMap()
    watchdog.beat("harvest+seed")
    # 0+1. FRONT-LOAD the spoken-word entity map (brief 29 — harvest checkable nouns from YouTube +
    #    podcasts so the leads start lead-rich) AND seed the map with a web hunt. These are INDEPENDENT
    #    — the entities feed the LEADS, which come after both — so OVERLAP them (task #20 lever 1):
    #    the seed hunt runs during the harvest's transcription wait instead of after it.
    def _harvest():
        return harvest_entities(subject, branch_id=branch_id, recency_years=recency_years,
                                seed_entities=seed_entities)
    def _seed():
        return hunt(subject, branch_id=branch_id, max_pages=per_lead_pages,
                    recency_years=recency_years, entities=seed_entities)
    if parallel:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_ent, f_seed = ex.submit(_harvest), ex.submit(_seed)
            entities = f_ent.result() or []
            f_seed.result()
    else:
        entities = _harvest()
        _seed()
    watchdog.beat("case-plan")
    # 2. case plan (the diligence checklist)
    plan = build_case_plan(subject)
    plan_leads = targeted_questions(plan, max_q=max_leads)
    seeds = [str(e).strip() for e in (seed_entities or []) if str(e).strip()]
    cap = max_leads
    if seeds:
        # KNOWN roster — EVERY seeded entity gets its own mandatory verification lead (completeness
        # guaranteed, not left to discovery). Surface them in the dossier entity map too. The ceiling
        # expands to fit every seed plus a few pattern/base-rate leads on top.
        entities = list(dict.fromkeys(seeds + (entities or [])))
        # SHORT + SEARCHABLE (2026-07-27): was 17 words of instruction scaffolding wrapped around a
        # name, which every engine adapter then had to strip back off. Ask it the way a
        # detective would type it; the primary-source standard belongs to the ANSWER, not the
        # question text.
        # ROTATED OPENING ANGLES (2026-07-28). The Challenger caught v16's opening set as
        # "template-monoculture: 2 distinct openings across 12 questions — this is a form being
        # filled in, not questions being asked." It was right, and the cost is not cosmetic: ten
        # identical stems means every person is probed from exactly ONE angle, so every person gets
        # the same slice of the web. Rotating genuinely different openings widens retrieval per
        # person (a "last seen" query and an "officials said" query land on different pages).
        # NEUTRAL by construction (Ghost): none presumes death or disappearance, because at wave-1
        # the status is exactly what we do not yet know.
        _ANGLES = ["What happened to {n}?",
                   "Where and when was {n} last seen?",
                   "Who last had contact with {n}?",   # not "missing or found" — the gate correctly
                   # flagged that as two questions in one, ambiguous for retrieval
                   "Which agency is investigating {n}'s case?",   # not "what have officials said" — the
                   # Challenger flagged that as retrieval-vague, and v16/v17 proved it: it pulled
                   # 61 findings about the WRONG Steven Garcia. Naming a concrete thing (the
                   # agency) is far harder for a namesake to match.
                   "What is the documented status of {n}?",
                   "What did {n} do for work before the incident?",
                   # RESEARCH SUBJECT (Gambit, 2026-07-28): "is there any correlation to what the
                   # scientists were studying?" The rotation asked about EMPLOYER but never about
                   # the WORK ITSELF, so the connections engine could only ever find 'both at JPL'.
                   # Ask what each person actually researched, so topic overlap becomes checkable.
                   "What was {n} researching or working on?"]
        entity_leads = [_ANGLES[i % len(_ANGLES)].format(n=e) for i, e in enumerate(seeds)]
        # ROSTER-EXPANSION, ASKED FIRST (Gambit, 2026-07-28): "a better introduction question would
        # probably have been: is there more than these people we've listed? if so, which ones?" He is
        # right, and v15 proved it — Claudio Manuel Neves Valente was the single most interesting
        # thread in the run and arrived by ACCIDENT through a follow-up, not because we asked. The
        # discovery organ still runs LATE (it needs a full corpus to clear the corroboration floor —
        # running it early promoted zero in v8), but the QUESTION belongs at the front so any name it
        # surfaces enters the corpus in wave 1 and can earn its own leads, question bank and
        # follow-ups instead of being a late bolt-on. Neutral: asks who ELSE is named, not who did it.
        entity_leads.insert(0, f"Who else is named in this cluster besides these {len(seeds)} people?")
        cap = max(max_leads, len(entity_leads) + 5)
    else:
        # discovery path — front-load the top harvested entities, reserving room for plan leads
        ent_cap = min(len(entities), max(2, max_leads // 2))
        entity_leads = [f"What is {e}'s documented role in this case?" for e in entities[:ent_cap]]
    ent_set, merged, seen = set(), [], set()
    for q in entity_leads:
        if q and q not in seen:
            seen.add(q); merged.append(q); ent_set.add(q)
    for q in plan_leads:
        if q and q not in seen:
            seen.add(q); merged.append(q)
    leads = merged[:cap]
    # PRE-FLIGHT QUESTION GATE (task #33): every lead drives real fetch spend, so grade the questions
    # BEFORE the money — C/F leads get rewritten into sharp, retrievable questions (Gambit: 'the
    # fetcher depends on every question asked'). One cheap LLM call; fail-open.
    from . import search_queries as _sq
    leads = _sq.preflight_gate(leads, context=subject)
    # CHECKPOINT 1 — BEFORE a single fetch. If the opening questions are unusable, stop here: this
    # costs seconds, whereas finding out at the write-up costs an hour and ~400 credits (Marcus).
    _cp1 = _challenge_checkpoint("wave-1 opening questions", "questions", leads, case=subject,
                                 claim="These opening questions are investigator-grade and will "
                                       "retrieve the case facts.")
    # ADD the gate's corrections to the opening set — the earliest and cheapest point to steer.
    _corr_cap = int(_os.environ.get("SEEKER_CORRECTION_LEADS", "4"))
    _corr = [c for c in (_cp1.get("corrections") or []) if c not in leads][:_corr_cap]
    if _corr:
        print(f"  ↳ CHALLENGER added {len(_corr)} corrective question(s): "
              + " | ".join(c[:60] for c in _corr), flush=True)
        leads = list(leads) + _corr
    # 3. drive DEEP against each lead + counter-evidence — concurrently (task #18).
    # RECENCY DISCIPLINE (2026-07-20): a person's identity / death / outcome is a TIMELESS fact — the
    # topical recency window must NEVER apply to entity-verification leads, or an older event (e.g. a
    # 2022 death) is filtered out before it can be read. This buried Amy Eskridge's documented 2022
    # suicide on a run capped at recency_years=2. Entity leads run UNFILTERED; only the topical plan
    # leads honor recency.
    ent_leads = [q for q in leads if q in ent_set]
    top_leads = [q for q in leads if q not in ent_set]
    coverage = []
    if ent_leads:
        coverage += _drive_leads(ent_leads, parallel=parallel, branch_id=branch_id,
                                 per_lead_pages=per_lead_pages, recency_years=None, mm=mm)
    if top_leads:
        coverage += _drive_leads(top_leads, parallel=parallel, branch_id=branch_id,
                                 per_lead_pages=per_lead_pages, recency_years=recency_years, mm=mm)
    # 3b. WAVE-2 QUESTIONING (task #33) — the Mind, finally wired in. A real investigator asks, READS,
    # then asks a SHARPER question; Seeker asked everything up front. Now that wave-1 findings are on
    # the map, the Mind (the question-generation brain built in brief 05, orphaned since) reads the
    # accumulated findings + gaps and generates frontier questions — scored on disagreement/frontier/
    # novelty/load-bearing/tractability, deduped against the question ledger, Council-Lite-vetted.
    # Top-scored few get driven as extra leads. UNFILTERED recency: wave-2 chases specific facts we
    # just learned (the Eskridge lesson — never blinder a follow-up). Fail-open.
    watchdog.beat("wave-2-questions")
    try:
        from .mind.mind import generate_next_questions
        w2 = generate_next_questions(subject, branch_id=branch_id, n=6)
        # GATE wave-2 too (2026-07-27): these bypassed preflight_gate entirely, and the Mind's
        # output was the WORST in v14 (35-word document-existence interrogatories). Every lead set
        # that costs money now passes the same gate.
        w2_leads = _sq.preflight_gate([r["q"] for r in w2[:4] if r.get("q")], context=subject)
        _challenge_checkpoint("wave-2 (the Mind)", "questions", w2_leads, case=subject,
                              claim="The Mind's next questions push the frontier and are searchable.")
    except Exception:
        w2_leads = []
    if w2_leads:
        coverage += _drive_leads(w2_leads, parallel=parallel, branch_id=branch_id,
                                 per_lead_pages=per_lead_pages, recency_years=None, mm=mm)
    # 3d. INTERROGATION LOOP (task #35) — the questioning loop, Seeker's actual differentiator. Draw
    # connections on what we have, then let each CONNECTION raise its own next questions (a link is a
    # LEAD to chase — 'both tied to AFRL: did their dates overlap? which program?' — not a finished
    # result), and deepen the people those connections involve with a real investigator's question
    # bank. Chase the best follow-ups; the write-up's connections/synthesis then read the deeper map.
    # BOUNDED (Marcus): questions are pennies but FETCHES are dollars — grade + cap the driven set.
    _cap = int(_os.environ.get("SEEKER_INTERROGATION_LEADS", "8"))
    watchdog.beat("interrogation")
    try:
        from . import interrogate as _intg
        from . import connections as _conn0
        early_conns = _conn0.find_connections(subject, branch_id=branch_id, mm=mm)
        followups = _intg.questions_from_connections(subject, early_conns, n=6)
        involved = {e for c in early_conns.get("connections", []) for e in c.get("entities", [])}
        for e in list(involved)[:8]:              # deepen the people the connections actually point at
            followups += _intg.question_bank(subject, e, n=3, branch_id=branch_id, mm=mm)[:1]
        followups = _sq.preflight_gate(followups, context=subject)[:_cap]
    except Exception:
        followups = []
    if followups:
        coverage += _drive_leads(followups, parallel=parallel, branch_id=branch_id,
                                 per_lead_pages=per_lead_pages, recency_years=None, mm=mm)
    # 3e. ROSTER DISCOVERY (task #34) — find case subjects we were NEVER told about. Runs LATE, on the
    # FULLEST corpus (after wave-1/2 + interrogation), because it needs enough mentions to clear the
    # corroboration floor — running it early (v8 bug) promoted ZERO since candidates were all thin.
    # Harvest candidate names, classify each against ITS OWN evidence, promote only genuine case
    # subjects (a commentator/relative mislabelled a victim is real harm: Ghost). Discovered names are
    # UNVERIFIED and earn their own verification lead. Fail-open.
    watchdog.beat("roster-discovery")
    from . import discovery as _disc
    discovered = _disc.discover_roster(subject, entities, branch_id=branch_id, mm=mm)
    new_names = [c["name"] for c in discovered.get("candidates", [])][:6]
    if new_names:
        entities = list(dict.fromkeys(list(entities) + new_names))
        disc_leads = _sq.preflight_gate(
            [f"What happened to {n}? Documented status and cause." for n in new_names], context=subject)
        coverage += _drive_leads(disc_leads, parallel=parallel, branch_id=branch_id,
                                 per_lead_pages=per_lead_pages, recency_years=None, mm=mm)
    # 3e-2. THE FOLLOW-UP HOP (Gambit, 2026-07-27) — the loop the app never actually had.
    #
    # Until now Seeker asked a question, fetched the answer, and moved on. Nothing read an ANSWER and
    # asked what IT raised, so the run surfaced 'Reza was last seen waving to a companion ~30 feet
    # away' and 'Chavez left on foot on 37th Street' and then dropped both threads. Three waves of
    # questions is not a loop; a loop keeps pulling until the thread runs out.
    #
    # Shape (Gambit's own call — a PROMPT, not a new organ): take the leads that actually produced
    # findings, hand each answer back to interrogate.follow_ups, drive what comes out, repeat.
    # Bounded three ways (Marcus/Noor): only leads that YIELDED get chased (never a dead end), a hard
    # total-question ceiling, and a stop as soon as a round produces nothing new. Fail-open.
    _fu_rounds = int(_os.environ.get("SEEKER_FOLLOWUP_ROUNDS", "2"))
    _fu_cap = int(_os.environ.get("SEEKER_FOLLOWUP_LEADS", "14"))
    follow_up_trace = []          # [{round, parent, child, findings}] — so the loop is INSPECTABLE
    try:
        from . import interrogate as _intg_fu
        _asked = {str(r.get("lead", "")).lower() for r in coverage if r.get("lead")}
        _frontier = [r for r in coverage if r.get("covered") and r.get("claims")]
        _spent = 0
        for _round in range(max(0, _fu_rounds)):
            if not _frontier or _spent >= _fu_cap:
                break
            watchdog.beat(f"follow-up-round-{_round + 1}")
            # richest answers first — the ones most likely to have opened a door
            _frontier.sort(key=lambda r: -int(r.get("findings", 0)))
            _next = []
            for _row in _frontier[:8]:
                if _spent + len(_next) >= _fu_cap:
                    break
                for _c in _intg_fu.follow_ups(subject, _row["lead"], _row.get("claims") or [],
                                              n=2, already_asked=_asked):
                    if _c.lower() not in _asked:
                        _asked.add(_c.lower())
                        _next.append((_row["lead"], _c))
            _next = _next[:max(0, _fu_cap - _spent)]
            if not _next:
                break                      # nothing new opened — the thread is exhausted, stop
            _child_qs = _sq.preflight_gate([c for _p, c in _next], context=subject)
            _challenge_checkpoint(f"follow-up round {_round + 1}", "questions", _child_qs,
                                  case=subject,
                                  claim="These follow-ups chase a NEW specific detail from the answer.",
                                  expected="each follow-up pulls on a concrete detail that just "
                                           "appeared (a name, time, place or object) rather than "
                                           "rephrasing the question it came from")
            _rows = _drive_leads(_child_qs, parallel=parallel, branch_id=branch_id,
                                 per_lead_pages=per_lead_pages, recency_years=None, mm=mm)
            coverage += _rows
            _spent += len(_child_qs)
            for (_parent, _child), _r in zip(_next, _rows):
                # record what was actually DRIVEN (the gate may have rewritten the child) — the
                # trace must reflect reality, not the pre-rewrite draft (Vera)
                follow_up_trace.append({"round": _round + 1, "parent": _parent,
                                        "child": str(_r.get("lead", _child)),
                                        "findings": int(_r.get("findings", 0))})
            # the answers we just got become the next frontier
            _frontier = [r for r in _rows if r.get("covered") and r.get("claims")]
    except Exception:
        pass

    # 3f. DEPTH EQUALIZATION (Gambit, 2026-07-23) — spend effort where the case is COLD, not where
    # the web is already loud. v9 exposed the skew: McCasland (Feb 2026, heavily covered) drew 19
    # mentions while Eskridge (2022), Sullivan and LeBlanc drew 2 each — a ~10:1 depth gap inside one
    # investigation. Root cause: wave-2 only deepened people the CONNECTIONS pointed at, so a thin
    # person could never qualify and the rich got richer. A real investigator does the opposite.
    #
    # Bounded by EFFORT, never by results (Noor): a genuinely undocumented person must not loop
    # forever, so each under-covered name gets a fixed number of extra probes and we stop — thin
    # output then honestly reflects a thin public record. Questions are pennies, fetches are dollars
    # (Marcus): hard cap on extra leads + 2 rounds max, env-tunable. Fail-open.
    _eq_cap = int(_os.environ.get("SEEKER_EQUALIZE_LEADS", "12"))
    _eq_rounds = int(_os.environ.get("SEEKER_EQUALIZE_ROUNDS", "2"))
    depth_equalization = {"before": {}, "after": {}, "targeted": [], "extra_leads": 0}
    try:
        from . import entity_profiles as _ep_eq   # call by name (not an alias) so the wiring
        from . import interrogate as _intg_eq     # orphan-guard can prove this organ FIRES
        from . import identity as _identity        # identity anchoring (task #41)
        # ROSTER = the seeded PEOPLE plus discovery-promoted people ONLY — never `entities`, which by
        # here also holds harvested nouns (places/orgs/units). v10 bug: `entities` leaked 'Mount
        # Waterman', 'Air Rescue 5', 'Crescenta Valley Station' into the top-up, spending cold-case
        # budget on a mountain and a helicopter unit instead of the thin PEOPLE it's meant for.
        _people = list(dict.fromkeys(seeds + [n for n in new_names]))
        roster = [str(e).strip() for e in _people if str(e).strip()]
        # CASE ANCHOR reused from the run-scoped value computed at question-forming (one source, no
        # drift) — disambiguates a thin person's probes from a namesake (v11: 'Joshua LeBlanc' pulled
        # 19 wine-tourism papers by an academic of the same name; the anchor keeps probes on the
        # right person).
        # IDENTITY CARDS (task #41) — the per-person replacement for the shared case anchor. One
        # anchor for thirteen people distinguishes none of them from their OWN namesakes; a card
        # gives each person their own employer/role/place/years. Built from findings we already
        # hold, so it costs one batched call and no extra searching. Printed live: a wrong card is
        # visible while it can still be corrected, not discovered in the finished report (Noor's
        # inversion risk — a card built from contaminated findings would quarantine the truth).
        _id_cards = {}
        if roster:
            try:
                _id_cards = _identity.build_cards(subject, roster, branch_id=branch_id, mm=mm)
                print(_identity.format_cards(_id_cards), flush=True)
                from .hunt import seeker_agent as _sa_cards   # the bulk search lanes were the leak
                _sa_cards.set_identity_cards(_id_cards)
            except Exception:
                _id_cards = {}
        identity_screen = {"quarantined": [], "cards": _id_cards}
        if roster and _eq_cap > 0:
            watchdog.beat("depth-equalization")
            counts = _ep_eq.findings_per_entity(subject, roster, branch_id=branch_id, mm=mm)
            depth_equalization["before"] = dict(counts)
            spent = 0
            for _rnd in range(max(0, _eq_rounds)):
                if not counts or spent >= _eq_cap:
                    break
                vals = sorted(counts.values())
                med = vals[len(vals) // 2] if vals else 0
                # relative floor scales with the case (a rich case deserves a higher bar than a thin
                # one); the absolute 3 keeps us from chasing noise on a uniformly-thin corpus.
                floor = max(3, int(med * 0.5))
                thin = [n for n, c in sorted(counts.items(), key=lambda kv: kv[1]) if c < floor]
                if not thin:
                    break
                eq_leads = []
                for nm in thin:
                    if spent + len(eq_leads) >= _eq_cap:
                        break
                    # reuse the per-person interrogation bank — no new query text to drift (Zara)
                    # DISAMBIGUATED probes: NAME + case-anchor + angle, so a common name resolves to
                    # the person in THIS case, not a namesake. person_queries applies the anchor to
                    # every angle query now (search_queries fix). Falls back to question_bank text.
                    # PER-PERSON anchor first, shared case anchor only as fallback: "Nuno Loureiro
                    # MIT plasma physicist" beats "Nuno Loureiro missing scientists", which is what
                    # twelve other people were also being asked as.
                    _ctx = _identity.disambiguator(_id_cards.get(nm) or {}) or _case_anchor
                    qs = _sq.person_queries(nm, context=_ctx,
                                            angles=["cause of death", "missing", "death"], max_q=2)
                    if not qs:
                        qs = _intg_eq.question_bank(subject, nm, n=2, branch_id=branch_id, mm=mm)[:2]
                    eq_leads += [q for q in qs if q]
                    if nm not in depth_equalization["targeted"]:
                        depth_equalization["targeted"].append(nm)
                eq_leads = _sq.preflight_gate(eq_leads, context=subject)[:max(0, _eq_cap - spent)]
                if not eq_leads:
                    break
                # recency=None: a person's fate is timeless — same discipline as entity leads
                coverage += _drive_leads(eq_leads, parallel=parallel, branch_id=branch_id,
                                         per_lead_pages=per_lead_pages, recency_years=None, mm=mm)
                spent += len(eq_leads)
                counts = _ep_eq.findings_per_entity(subject, roster, branch_id=branch_id, mm=mm)
            depth_equalization["after"] = dict(counts)
            depth_equalization["extra_leads"] = spent
        # IDENTITY SCREEN + RECONSTRUCTED SEARCH (task #41). Test what we gathered against each
        # card and QUARANTINE year-contradictions — a claim dating a death to 2013 cannot describe
        # a person the card has dying in 2025, and that is arithmetic, not a judgment a model can be
        # argued out of. A quarantine is not a deletion: the finding is reported with its reason,
        # and the person is RE-SEARCHED with a tightened query, so the pass adds evidence rather
        # than only subtracting it (the rule the Challenger gate settled on).
        try:
            if _id_cards and any(_identity.disambiguator(c) or c.get("died") for c in _id_cards.values()):
                watchdog.beat("identity-screen")
                _sbuckets = _syn.gather_findings(subject, branch_id=branch_id, mm=mm)
                _all_f = []
                for _lab in ("well-supported", "contested", "unverified"):
                    _all_f += _sbuckets.get(_lab, [])
                _retry = []
                for _nm, _card in _id_cards.items():
                    _keys = _ep_eq._entity_keys(_nm)
                    _mine = [f for f in _all_f
                             if any(k in (f.get("claim", "") or "").lower() for k in _keys)]
                    _kept, _quar = _identity.screen(_mine, _card)
                    for _q in _quar:
                        identity_screen["quarantined"].append(
                            {"name": _nm, "claim": (_q.get("claim") or "")[:200],
                             "reason": _q.get("quarantine_reason", "")})
                    if _quar:
                        _retry += _identity.retry_queries(_card, max_q=2)
                if identity_screen["quarantined"]:
                    print("— IDENTITY SCREEN — %d finding(s) quarantined as a DIFFERENT person:"
                          % len(identity_screen["quarantined"]), flush=True)
                    for _q in identity_screen["quarantined"][:10]:
                        print("   [%s] %s\n        why: %s"
                              % (_q["name"][:24], _q["claim"][:96], _q["reason"]), flush=True)
                    _retry = _sq.preflight_gate(_retry, context=subject)[:8]
                    if _retry:
                        print("— RE-SEARCHING with tightened identity anchors (%d queries) —"
                              % len(_retry), flush=True)
                        coverage += _drive_leads(_retry, parallel=parallel, branch_id=branch_id,
                                                 per_lead_pages=per_lead_pages,
                                                 recency_years=None, mm=mm)
                else:
                    print("— IDENTITY SCREEN — no year-contradictions; roster reads as one person each",
                          flush=True)
        except Exception as _e:
            print(f"[identity-screen skipped: {_e}]", flush=True)
            _organ_failed("identity-screen", _e, subject=subject, branch_id=branch_id)
    except Exception:
        pass

    watchdog.beat("write-up")
    # 3g. CONTRIBUTION LANE (task #41) — one last ask: does a second retrieval path hold documented
    # detail our map lacks? Perplexity as a CONTRIBUTOR, never a judge (Chris's framing): a judge
    # would cap Seeker at the judge's ceiling. Everything it returns enters UNVERIFIED, as atomic
    # claims rather than prose, and passes the same namesake screen as any other source.
    contribution = {}
    try:
        if _os.environ.get("SEEKER_CONTRIBUTE", "1") != "0":
            from . import contribute as _contrib
            watchdog.beat("contribution")
            _known = [f["claim"] for f in _syn.all_findings(branch_id, mm)]
            contribution = _contrib.contribute(subject, roster if 'roster' in dir() else entities,
                                               _known, cards=_id_cards, branch_id=branch_id)
            print(_contrib.format_contribution(contribution), flush=True)
            if contribution.get("findings"):
                upsert_findings_consolidated(mm, contribution["findings"], branch_id=branch_id)
    except Exception as _e:
        print(f"[contribution skipped: {_e}]", flush=True)
        _organ_failed("contribution", _e, subject=subject, branch_id=branch_id)

    # 3h. CASE FILES + TRIAGE (Chris's design) — EVERY finding is reviewed and given a verdict
    # before anything is written. Until now the write-up read a relevance slice and the rest of the
    # map was simply never looked at: on v19, 177 of 677 nodes went unread, including a 15-source
    # fact about McCasland — while a Tennessee heroin case matched on "Sullivan COUNTY" sat in the
    # corpus with equal standing. Gathering is expensive and reading is cheap; review all of it.
    triage = {}
    try:
        from . import case_files as _cf
        watchdog.beat("case-file triage")
        triage = _cf.triage_all(entities, branch_id=branch_id, mm=mm, cards=_id_cards)
        print(_cf.format_triage(triage), flush=True)
        # what SURVIVED triage is the evidence the write-up should rest on. Reported, and carried
        # in the dossier so a reader can see the difference between what was gathered and what was
        # judged usable — the two numbers should never again be silently the same.
        # BIND the verdicts: every organ downstream now reads the map WITHOUT the rejects. Until
        # this line existed the triage was decorative — organs re-read the full map regardless.
        _rejected = [r.get("id") for rows in triage.get("files", {}).values()
                     for r in rows if r.get("verdict") == "reject"]
        _syn.set_excluded(_rejected)
        print(f"  -> {len(set(_rejected))} findings excluded from every downstream organ", flush=True)
        _kept = _cf.useful(triage)
        print(f"  -> {len(_kept)} findings survived triage and feed the write-up", flush=True)
        triage["useful_ids"] = [f.get("id") for f in _kept]
    except Exception as _e:
        print(f"[case-file triage skipped: {_e}]", flush=True)
        _organ_failed("case-file-triage", _e, subject=subject, branch_id=branch_id)

    # 4. write up. ACH, synthesis, and the claim ledger each read the finished map INDEPENDENTLY,
    #    so run those three LLM passes CONCURRENTLY (task #20 lever 3) instead of one-after-another.
    #    open_threads runs AFTER — it consumes ach + ledger.
    from . import connections as _conn
    from . import disagreement as _dis
    def _ach():    return ach_score(subject, plan.get("hypotheses", []), branch_id=branch_id, mm=mm)
    # top_k=500, NOT 40 (fix 2026-07-28): v15 wrote its conclusion from 40 of 468 findings —
    # 91% of the evidence was invisible to it — and duly reported "Sullivan, Eskridge and LeBlanc
    # are not documented in the provided evidence" while the map held 4, 16 and 12 findings for
    # them. Third occurrence of the fixed-window-doesn't-scale bug (entity_profiles hit it at 70,
    # transcript scan at 40). The conclusion must see the whole case, not a keyhole.
    def _syn_():   return _syn.synthesize(subject, branch_id=branch_id, mm=mm)
    def _ledg():   return _cl.claim_ledger(subject, branch_id=branch_id, mm=mm)
    # INTEGRATION (task #27): Seeker's OWN cross-entity analysis + the disagreement structure now
    # fire in EVERY flagship run — independent map-reads, so they join the concurrent write-up.
    def _conns():  return _conn.find_connections(subject, branch_id=branch_id, mm=mm)
    def _disag():  return {"map": _dis.disagreement_map(subject, branch_id=branch_id, mm=mm),
                           "resolvers": _dis.what_would_resolve(subject, branch_id=branch_id, mm=mm)}
    if parallel:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=5) as ex:
            f_a, f_s, f_l = ex.submit(_ach), ex.submit(_syn_), ex.submit(_ledg)
            f_c, f_d = ex.submit(_conns), ex.submit(_disag)
            ach, syn, ledger = f_a.result(), f_s.result(), f_l.result()
            conns, disag = f_c.result(), f_d.result()
    else:
        ach, syn, ledger = _ach(), _syn_(), _ledg()
        conns, disag = _conns(), _disag()
    watchdog.beat("write-up:analysis-done")   # the write-up LLM passes are slow (REASONING_MODEL) —
    # keep beating between stages so a healthy-but-slow final phase can't trip the stall abort.
    # PATTERN-CLAIM ADJUDICATION (task #28) — fires AFTER connections so it can cross-reference each
    # claimed pattern against Seeker's OWN confirmed links + the claim-ledger facts. Answers "who thinks
    # they found a pattern, and does it hold up?" — the rigorous complement to our own empty link search.
    from . import pattern_claims as _pc
    pclaims = _pc.adjudicate_claimed_patterns(subject, branch_id=branch_id, mm=mm,
                                              connections=conns, claim_ledger=ledger.get("claims", []))
    watchdog.beat("write-up:pattern-claims-done")
    open_threads = _open_threads(subject, plan, coverage, ach, ledger.get("claims", []),
                                 mm, branch_id)
    # surface any 'unresolved-notable' claimed patterns as open threads — they are explicitly the ones
    # worth a reader's attention even though unproven (Gambit's rule).
    for p in pclaims.get("claimed_patterns", []):
        if p.get("verdict") == "unresolved-notable":
            note = p.get("why_notable") or p.get("why_unproven") or ""
            open_threads = open_threads + [f"UNRESOLVED-NOTABLE claim: {p['pattern']}"
                                           + (f" — {note}" if note else "")]
    # 4b. QUILL (integration #27) — the reporting layer fires in every flagship run: a fact-checked
    # long-form report + notable threads, then Quill's editor critiques it. Turns the dossier from a
    # data dump into shareable prose. Reads the finished, name-normalized map.
    # ENTITY RESOLUTION + PROFILES — MUST precede Quill, which now takes `profiles` as its factual
    # spine. This block used to sit ~50 lines BELOW the Quill call: `profiles` was wired into the
    # report and the assignment was left where it was, so every flagship run reached the write-up and
    # died on UnboundLocalError (v19, after 1h29m of completed searching). The searching was fine —
    # only the final assembly crashed. Ordering, not logic: a name must be bound before it is read.
    try:
        from .entity_resolution import cluster_entities
        seed_set = {s.lower() for s in seeds}
        ments = [(e, (e.lower() in seed_set)) for e in entities]
        clusters = cluster_entities(ments)
        entities = [c["canonical"] for c in clusters if not c["suspect"]]
    except Exception:
        pass
    from . import entity_profiles as _profiles
    profiles = _profiles.entity_profiles(subject, entities, branch_id=branch_id, mm=mm)
    from . import quill as _quill
    watchdog.beat("write-up:quill")           # Quill = draft + fact-check + critique + revise + re-check
    # WIRE-DOSSIER (task #38) — the linear write-up that produced the first PUBLISH in twenty runs.
    # It replaces the self-editing Quill chain as the primary: draft -> gates -> at most ONE
    # corrective pass -> review -> stop. Quill remains the fallback, so a failure here still yields
    # a report rather than nothing.
    from . import wire_report as _wire
    report = {}
    try:
        _w = _wire.build(subject, profiles, ledger=ledger.get("claims", []), roster=entities)
        report = {"report": _w["report"], "corrections": [],
                  "voice_violations": _w["voice_violations"],
                  "fidelity_violations": _w["fidelity_violations"],
                  "publisher_review": _w["review"], "corrective_passes": _w["corrective_passes"],
                  "form": "wire-dossier"}
        print(f"— WRITE-UP — voice {len(_w['voice_violations'])} · "
              f"fidelity {len(_w['fidelity_violations'])} · "
              f"reviewer {_w['review'].get('verdict','?')}", flush=True)
    except Exception as _e:
        print(f"[wire-dossier failed, falling back to Quill: {_e}]", flush=True)
        _organ_failed("wire-dossier", _e, subject=subject, branch_id=branch_id)
    if not report.get("report"):
        report = _quill.report(subject, branch_id=branch_id, mm=mm, profiles=profiles)
    watchdog.beat("write-up:quill-done")
    report["critique"] = _quill.critique(report.get("report", "")) if report.get("report") else {}
    # 4c. PUBLISHER-REVIEWER (task #37) — the last INDEPENDENT gate before this could be published.
    # Quill's critique asks "does this read well?"; this asks "is this HONEST?" — softening a
    # documented finding, stripping meaning-changing context, false balance, loaded framing,
    # selective citation, and the hard blocker: asserting a named person's guilt (Ghost). Run by a
    # DIFFERENT model than the writer, because the model that softened the prose is the last one that
    # will notice (Noor). Advisory + visible: a 'revise' verdict is surfaced in the dossier, never a
    # silent pass, and it never rewrites or blocks the run itself.
    watchdog.beat("write-up:publisher-review")
    from . import publisher_reviewer as _pubrev
    report["publisher_review"] = _pubrev.review(
        report.get("report", ""), question=subject, roster=entities,
        writer_model=getattr(_quill, "_QUILL_MODEL", "")) if report.get("report") else {}
    # 5. COMPLETENESS gate — only when the roster was NOT seeded (a seeded run is complete by
    #    construction). Diff our investigated entities against a canonical enumeration; any names the
    #    authoritative source lists but we never investigated become an explicit warning thread. This
    #    is the fix for the failure where discovery surfaced only the prominent names (correctness !=
    #    completeness). Fail-open; flagged names are 'possibly missing', not asserted facts.
    # ALWAYS run the completeness gate (task #34). It used to be gated behind `if not seeds:` on the
    # assumption that "a seeded run is complete by construction" — that assumption is FALSE and it
    # silently disabled discovery on every real (seeded) investigation we ever ran. A seeded roster is
    # what the CALLER knew, not what is true.
    completeness = check_completeness(subject, entities, branch_id=branch_id,
                                      recency_years=recency_years)
    if completeness.get("missing"):
        open_threads = ([f"COMPLETENESS WARNING — authoritative sources name individuals we did "
                         f"not investigate: {', '.join(completeness['missing'][:12])}. Roster may "
                         f"be incomplete; consider re-running with these seeded."] + open_threads)
    # surface what discovery actually added (or considered and rejected) as an explicit thread —
    # a promoted name is an UNVERIFIED candidate, never an assertion (Vera).
    if discovered.get("candidates"):
        open_threads = ([f"DISCOVERED (unverified) — case subjects not in the supplied roster, now "
                         f"investigated: " + ", ".join(f"{c['name']} ({c['mentions']} mentions)"
                                                       for c in discovered["candidates"][:8])]
                        + open_threads)
    # entity-map display: resolve the raw (spoken-word-heavy) harvest list to a CANONICAL roster and
    # DROP the spoken-only garbles (e.g. 'Schiavo' when 'Chavez' was seeded) so the dossier shows a
    # clean roster, not the raw leads. Seeded names are authoritative; harvested ones are not.
    # corroboration-over-popularity ranking (integration #27) — the best-corroborated claims
    try:
        top_corr = mm.top_corroborated(subject, branch_id=branch_id, top_k=8)
    except Exception:
        top_corr = []
    contribution = _contribution_ledger(subject, branch_id, mm, ach=ach,
                                        ledger=ledger.get("claims", []), open_threads=open_threads,
                                        conclusion=syn.get("conclusion"), entities=entities,
                                        conns=conns, disag=disag, report=report, top_corr=top_corr,
                                        pclaims=pclaims)
    dossier = {"subject": subject, "topic_raw": raw_topic,
               "question_former": {"corrections": formed.get("corrections", []),
                                   "facts_used": formed.get("facts_used", False)},
               "plan": plan, "coverage": coverage,
               "entities": entities, "entity_profiles": profiles, "discovery": discovered, "ach": ach,
               "conclusion": syn["conclusion"],
               "buckets": {k: len(v) for k, v in syn["buckets"].items()},
               "claim_ledger": ledger.get("claims", []),
               "open_threads": open_threads, "completeness": completeness,
               "connections": conns, "disagreement": disag, "report": report,
               "pattern_claims": pclaims, "depth_equalization": depth_equalization,
               "next_questions": suggest_next_questions(subject, coverage, open_threads,
                                                        branch_id=branch_id, mm=mm),
               # embed-cache effectiveness for THIS run — so the next perf claim is measured, not
               # asserted. After v17 (predicted 2x, delivered 3%) estimates are not good enough.
               "embed_stats": (lambda: __import__("seeker.memory.memory_map", fromlist=["x"]).embed_stats())(),
               "challenger_review": list(_CHALLENGE_LOG),
               "follow_up_trace": follow_up_trace,
               "top_corroborated": top_corr, "contribution": contribution}
    # CAPSTONE (integration #27): Seeker generates its OWN shareable map from the dossier.
    from . import mapgen as _mapgen
    map_path = _mapgen.write_map(dossier, branch_id=branch_id)
    dossier["map_path"] = map_path
    contribution.append({"organ": "Auto-generated map", "added": map_path or "—",
                         "status": "firing" if map_path else "DEAD (not written)"})
    return dossier                         # watchdog disarmed by the run_investigation wrapper's finally
