"""Stdlib-only tests (no pytest dependency) for the 2026-07-16 autonomous-session builds.

Covers the PURE, network-free logic: podcast recency + relevance tokenisation, and an import
smoke test that every module touched this session loads cleanly. Run: `.venv/bin/python
tests/test_session_2026_07_16.py` — exits non-zero on any failure."""
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, "src")

_fails = []


def check(name, cond):
    print(("  ok  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


def test_recency():
    from seeker.recon import podcast
    mk = lambda d: ET.fromstring(f"<item><pubDate>{d}</pubDate></item>")
    check("recency: 2026 within 2y", podcast._within_recency(mk("Wed, 01 Jul 2026 12:00:00 +0000"), 2))
    check("recency: 2015 outside 2y", not podcast._within_recency(mk("Wed, 01 Jul 2015 12:00:00 +0000"), 2))
    check("recency: 2015 with None (unbounded)", podcast._within_recency(mk("Wed, 01 Jul 2015 12:00:00 +0000"), None))
    check("recency: undated passes", podcast._within_recency(ET.fromstring("<item/>"), 2))
    check("recency: malformed date passes (fail-open)", podcast._within_recency(mk("not-a-date"), 2))


def test_relevance_tokens():
    from seeker.recon import podcast
    # a specific topic token qualifies; a bare place word does not
    topic = podcast._sig_tokens("Monica Reza missing scientists Angeles National Forest")
    real = podcast._sig_tokens("Missing Scientists a true crime investigation")
    junk = podcast._sig_tokens("Turf Show Times for Los Angeles Rams fans")
    check("relevance: real feed shares specific token", bool((topic & real) - podcast._WEAK_TOKENS))
    check("relevance: junk feed shares only weak place word", not ((topic & junk) - podcast._WEAK_TOKENS))
    check("sig_tokens: drops short/scaffolding words", "the" not in topic and "monica" in topic)


def test_search_terms_fallback():
    from seeker.recon import podcast
    # heuristic fallback must yield a non-empty phrase even if the LLM is unreachable is not asserted
    # here (would need network); just confirm the pure tokeniser + weak set are wired
    check("weak tokens include 'angeles'", "angeles" in podcast._WEAK_TOKENS)
    check("weak tokens exclude 'scientists'", "scientists" not in podcast._WEAK_TOKENS)


def test_imports_smoke():
    mods = ["seeker.director", "seeker.claim_ledger", "seeker.recon.podcast",
            "seeker.memory.memory_map", "seeker.hunt.hunt", "seeker.synthesis"]
    import importlib
    for m in mods:
        try:
            importlib.import_module(m)
            check(f"import {m}", True)
        except Exception as e:
            check(f"import {m} ({repr(e)[:50]})", False)


def test_public_api_present():
    from seeker import director
    from seeker.memory.memory_map import MemoryMap
    check("director.harvest_entities exists", hasattr(director, "harvest_entities"))
    check("director._open_threads exists", hasattr(director, "_open_threads"))
    check("MemoryMap.organ_mix exists", hasattr(MemoryMap, "organ_mix"))
    check("MemoryMap.top_corroborated exists", hasattr(MemoryMap, "top_corroborated"))


def test_dossier_renderer():
    """The --director dossier renderer prints every signal section from a synthetic dossier."""
    import io
    import contextlib
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "inv", ".claude/skills/seeker-investigate/investigate.py")
    inv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inv)

    class FakeMM:
        def organ_mix(self, q, branch_id="main"):
            return {"web": 3, "podcast": 1}

    d = {"entities": ["Mondaloy", "McCasland"],
         "plan": {"hypotheses": ["Accident", "Foul play"], "anomalies": ["beanie only"]},
         "coverage": [{"lead": "verify alloy", "findings": 9, "covered": True},
                      {"lead": "dead lead", "findings": 0, "covered": False}],
         "ach": [{"hypothesis": "Accident", "verdict": "weakened"}],
         "claim_ledger": [{"claim": "alloy is real", "verdict": "verified",
                           "lean": "toward", "magnitude": "strong"},
                          {"claim": "foul play", "verdict": "unproven",
                           "lean": "balanced", "magnitude": "slight"}],
         "open_threads": ["date conflict 2025 vs 2023"],
         "conclusion": "Most plausibly an accident."}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        inv._render_dossier(d, FakeMM(), "b", "Test subject")
    o = buf.getvalue()
    for section in ("ENTITY MAP", "CASE PLAN", "COVERAGE", "COMPETING HYPOTHESES",
                    "CLAIM LEDGER", "OPEN THREADS", "ORGAN MIX", "CONCLUSION"):
        check(f"renderer prints {section}", section in o)
    check("renderer shows directional lean", "strong toward" in o)
    check("renderer shows balanced as em-dash", "lean:               —" in o or "—" in o)
    check("renderer shows organ mix counts", "web:3" in o and "podcast:1" in o)
    check("renderer marks uncovered lead", "[ ] (  0) dead lead" in o)


def test_confidence_backbone():
    """The truth-standard math: independence weighting, triangulation, tier mapping, labels."""
    from seeker.memory import confidence as cf
    # LLM bloc collapses to ONE correlated vote; independent sources count fully
    check("independent: 3 LLMs = 1 vote", cf.independent_evidence(["llm", "llm", "llm"]) == 1)
    check("independent: llm+web+youtube = 3", cf.independent_evidence(["llm", "web", "youtube"]) == 3)
    check("independent: 2 web = 2", cf.independent_evidence(["web", "web"]) == 2)
    # tier math
    check("tier: 3 -> Accepted", cf.tier_for_source_count(3) == "Accepted")
    check("tier: 2 -> Moderately Accepted", cf.tier_for_source_count(2) == "Moderately Accepted")
    check("tier: 1 -> Speculative", cf.tier_for_source_count(1) == "Speculative")
    # triangulation: same family is an echo, distinct families cross-verify
    check("triangulation: 2 LLMs not triangulated", not cf.is_triangulated(["llm", "llm"]))
    check("triangulation: llm+youtube triangulated", cf.is_triangulated(["llm", "youtube"]))
    check("triangulation: None fails open (True)", cf.is_triangulated(None))
    # public label vocabulary
    check("label: Accepted -> well-supported", cf.standard_label("Accepted") == "well-supported")
    check("label: Controversial -> contested", cf.standard_label("Controversial") == "contested")
    check("label: unknown -> unverified", cf.standard_label("Nonsense") == "unverified")


def test_recency_windows():
    from seeker.recon import recency
    check("freshness: rapid -> 2y", recency.years_for_freshness("rapid") == 2)
    check("freshness: annually -> 5y", recency.years_for_freshness("annually") == 5)
    check("freshness: stable -> None", recency.years_for_freshness("stable") is None)
    check("freshness: None -> None", recency.years_for_freshness(None) is None)
    check("start_date: 0/None -> None (all time)", recency.start_date(0) is None)
    sd = recency.start_date(2)
    check("start_date: N years -> ISO string", isinstance(sd, str) and sd.endswith("Z"))


def test_neutrality_gate():
    from seeker import neutrality
    check("sensitive: 'vaccine' fires", neutrality.sensitive_topic("is the vaccine safe"))
    check("sensitive: 'election' fires", neutrality.sensitive_topic("who won the election"))
    check("sensitive: 'IQ scores' fires (fixed dead key)", neutrality.sensitive_topic("do IQ scores differ"))
    check("sensitive: 'unique' does NOT falsely fire", not neutrality.sensitive_topic("a unique recipe"))
    check("sensitive: neutral topic quiet", not neutrality.sensitive_topic("best sorting algorithm"))
    check("frame: prepends protocol + question", "QUESTION:" in neutrality.frame("test q"))


def test_models_id():
    from seeker.models import _id
    a, b = _id("find"), _id("find")
    check("_id: prefixed", a.startswith("find_"))
    check("_id: unique", a != b)
    check("_id: 12-hex suffix", len(a.split("_")[1]) == 12)


def test_parallel_lead_dispatch():
    """Task #18: _drive_leads runs leads concurrently, preserves order, covers all — no API calls."""
    import time
    from seeker import director
    orig = director._drive_lead
    try:
        director._drive_lead = lambda q, **kw: (time.sleep(0.3),
                                                {"lead": q, "findings": 1, "covered": True})[1]
        leads = [f"lead-{i}" for i in range(6)]
        t = time.time()
        serial = director._drive_leads(leads, parallel=False, branch_id="b",
                                       per_lead_pages=1, recency_years=None, mm=None)
        serial_t = time.time() - t
        t = time.time()
        par = director._drive_leads(leads, parallel=True, branch_id="b",
                                    per_lead_pages=1, recency_years=None, mm=None)
        par_t = time.time() - t
        check("parallel preserves lead order", [c["lead"] for c in par] == leads)
        check("parallel covers all leads", len(par) == 6 and all(c["covered"] for c in par))
        check("parallel is meaningfully faster than serial", par_t < serial_t / 2)
        check("single lead / parallel=False path works", len(
            director._drive_leads(["only"], parallel=True, branch_id="b",
                                  per_lead_pages=1, recency_years=None, mm=None)) == 1)
    finally:
        director._drive_lead = orig


def test_completeness_namediff():
    """The completeness gate: extract proper names + flag ones present canonically but not found."""
    from seeker.director import _names_from
    blob = "The list includes Monica Jacinto Reza, Steven Garcia, and Carl Grillmair."
    canon = _names_from(blob)
    check("names: multi-word proper names extracted",
          {"monica jacinto reza", "steven garcia", "carl grillmair"} <= canon)
    check("names: single-word / lowercase not captured", "the" not in canon and "list" not in canon)
    found = {"monica jacinto reza", "steven garcia"}
    missing = [c.title() for c in canon if not any(c in f or f in c for f in found)]
    check("completeness: flags the uninvestigated name", missing == ["Carl Grillmair"])
    check("director.check_completeness exists", hasattr(__import__("seeker.director", fromlist=["x"]),
                                                        "check_completeness"))


def test_connections_graph():
    """Connections Engine: entity index + shared-org co-occurrence (pure, no network)."""
    from seeker.connections import entity_index, _shared_org_pairs
    findings = [{"claim": "Monica Reza co-invented Mondaloy with the Air Force Research Laboratory."},
                {"claim": "William McCasland was former commander of the Air Force Research Laboratory."},
                {"claim": "Nuno Loureiro worked at MIT."}]
    idx = entity_index(findings)
    check("entity_index: extracts multi-word names", "Monica Reza" in idx["names"])
    check("entity_index: single-word noise excluded", "Mondaloy" not in idx["names"])
    sig = _shared_org_pairs(idx)
    afrl = [s for s in sig if "afrl" in s["org"] or "air force" in s["org"]]
    check("shared-org: detects AFRL co-occurrence signal", bool(afrl))
    check("connections module has find_connections", hasattr(
        __import__("seeker.connections", fromlist=["x"]), "find_connections"))


def test_entity_resolution():
    """The keystone (#23): variants of one person merge; garbled ones stay separate + flagged."""
    from seeker.entity_resolution import cluster_entities
    m = [("Monica Jacinto Reza", True), ("Monica Reza", True), ("Monica Jacinto", False),
         ("Anthony Chavez", True), ("Anthony Schiavo", False),
         ("William Neil McCasland", True), ("William Lee McCasland", False)]
    cl = cluster_entities(m)
    monica = [c for c in cl if "Monica" in c["canonical"]]
    check("resolution: 3 Monica variants merge to ONE entity",
          len(monica) == 1 and len(monica[0]["variants"]) == 3)
    check("resolution: canonical is the fullest form", monica and monica[0]["canonical"] == "Monica Jacinto Reza")
    mcc = [c for c in cl if "McCasland" in c["canonical"]]
    check("resolution: prefers authoritative spelling (Neil not Lee)",
          len(mcc) == 1 and mcc[0]["canonical"] == "William Neil McCasland")
    check("resolution: garbled distinct name stays separate",
          len([c for c in cl if c["canonical"] == "Anthony Chavez"]) == 1 and
          len([c for c in cl if c["canonical"] == "Anthony Schiavo"]) == 1)
    check("resolution: spoken-only unmatched name flagged suspect",
          any(c["canonical"] == "Anthony Schiavo" and c["suspect"] for c in cl))


def test_golden_case_dataflow():
    """OFFLINE integration guard (the 48h process fix): canned buckets with a variant + a garbled
    spoken-only fact, asserting the gather_findings pipeline (name normalization + spoken-word
    demotion) behaves — so this class of failure is caught without a 20-min live run."""
    from seeker.synthesis import _normalize_names, _demote_spoken_only
    buckets = {
        "well-supported": [
            {"id": "1", "claim": "Monica Reza worked at JPL.", "source_types": ["primary_source"]},
            {"id": "2", "claim": "Monica Jacinto Reza co-invented an alloy.", "source_types": ["web"]},
            {"id": "3", "claim": "Anthony Schiavo vanished near the lab.", "source_types": ["podcast"]},
        ],
        "contested": [], "unverified": [], "disproven": [],
    }
    # 1. name normalization: both Monica variants -> canonical, at the chokepoint
    norm = _normalize_names({k: [dict(f) for f in v] for k, v in buckets.items()})
    claims = " ".join(f["claim"] for f in norm["well-supported"])
    check("golden: Monica variants normalized to canonical",
          "Monica Jacinto Reza worked" in claims and claims.count("Monica Reza worked") == 0)
    # 2. spoken-only demotion: the podcast-only 'Schiavo' fact drops OUT of well-supported
    dem = _demote_spoken_only({k: [dict(f) for f in v] for k, v in buckets.items()})
    ws_ids = {f["id"] for f in dem["well-supported"]}
    check("golden: spoken-only fact demoted out of well-supported", "3" not in ws_ids)
    check("golden: spoken-only fact lands in unverified (kept as lead)",
          "3" in {f["id"] for f in dem["unverified"]})
    check("golden: corroborated facts stay well-supported", {"1", "2"} <= ws_ids)


def test_quill_present():
    from seeker import quill
    check("quill.report exists", hasattr(quill, "report"))
    check("quill._fact_check exists (fidelity guard)", hasattr(quill, "_fact_check"))
    check("quill.critique exists", hasattr(quill, "critique"))


if __name__ == "__main__":
    for t in (test_imports_smoke, test_recency, test_relevance_tokens,
              test_search_terms_fallback, test_public_api_present, test_dossier_renderer,
              test_confidence_backbone, test_recency_windows, test_neutrality_gate,
              test_models_id, test_parallel_lead_dispatch, test_completeness_namediff,
              test_connections_graph, test_quill_present, test_entity_resolution,
              test_golden_case_dataflow):
        print(t.__name__)
        t()
    print(f"\n{'ALL PASS' if not _fails else str(len(_fails)) + ' FAILED: ' + ', '.join(_fails)}")
    sys.exit(1 if _fails else 0)
