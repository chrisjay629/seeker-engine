import sys, os, json, inspect
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from seeker import watchdog; watchdog.start(threshold=900)

# ---- capture layer: record every outbound search query, never execute the search ----
RECORDS = []
def _who():
    for fr in inspect.stack()[2:14]:
        mod = fr.frame.f_globals.get("__name__", "")
        if mod.startswith("seeker.") and not fr.function.startswith("<"):
            return f"{mod.split('.')[-1]}.{fr.function}"
    return "unknown"

from seeker.hunt import seeker_agent, scholar
from seeker.recon import youtube, podcast
def rec(lane):
    def wrapper(orig):
        def inner(q, *a, **k):
            RECORDS.append({"lane": lane, "organ": _who(), "query": str(q)[:220]})
            return []
        return inner
    return wrapper
seeker_agent.exa_web_search = rec("WEB (Exa)")(seeker_agent.exa_web_search)
youtube.exa_youtube_search  = rec("YOUTUBE")(youtube.exa_youtube_search)
podcast.search_feeds        = rec("PODCAST")(podcast.search_feeds)
scholar.resolve             = rec("CITATION-GRAPH")(scholar.resolve)

from seeker import director
from seeker.hunt.hunt import hunt

SUBJECT=("The 2026 US House Oversight inquiry into missing and dead American scientists "
         "(NASA/JPL and Los Alamos personnel): is there a genuine COORDINATED pattern or a "
         "coincidental cluster — and which claims hold up against primary sources?")
ROSTER=["Monica Jacinto Reza","Amy Eskridge","Melissa Casias","William Neil McCasland","Nuno Loureiro"]

print("[1/3] generating queries from every organ (no searches executed)...", flush=True)
try: director.harvest_entities(SUBJECT, branch_id="qgrade", recency_years=4, seed_entities=ROSTER)
except Exception as e: print("  harvest note:", repr(e)[:60])
plan = director.build_case_plan(SUBJECT)
plan_leads = director.targeted_questions(plan, max_q=8)
ent_lead = ("Verify the identity, current status, and documented cause or outcome for this "
            "specific individual from primary/authoritative sources: Amy Eskridge")
for lead in [ent_lead, plan_leads[0] if plan_leads else ""]:
    if not lead: continue
    try: hunt(lead, branch_id="qgrade", max_pages=3, recency_years=None)
    except Exception as e: print("  hunt note:", repr(e)[:60])

# dedup per lane
seen, rows = set(), []
for r in RECORDS:
    k = (r["lane"], r["query"].lower())
    if k not in seen:
        seen.add(k)
        rows.append(r)

print(f"[2/3] grading {len(rows)} unique queries...", flush=True)
from seeker.memory.gap_detector import _reason_json
blob = "\n".join(f'{i}. [{r["lane"]} | {r["organ"]}] "{r["query"]}"' for i, r in enumerate(rows))
rubric = (
 "You are a search-quality grader. For each numbered SEARCH QUERY below (with the engine it goes to), "
 "grade how well it would retrieve relevant material on THAT engine, as a real person/investigator "
 "would search. Rubric:\n"
 "  A = natural search register, right length for the engine, has proper nouns/qualifiers; would land\n"
 "  B = decent; would work but could be sharper (missing place/date qualifier, slightly wordy)\n"
 "  C = weak; wrong register or vague, likely poor results\n"
 "  F = broken; instruction text, no payload, or would return systematically wrong results\n"
 "Engines: WEB (neural, tolerates prose), YOUTUBE + PODCAST (lexical, short keyword titles), "
 "CITATION-GRAPH (OpenAlex: matches academic PAPER TITLES only).\n"
 f"CASE CONTEXT: {SUBJECT[:160]}\n\n{blob}\n\n"
 'Return STRICT JSON: {"grades": [{"i": 0, "grade": "A", "why": "<max 12 words>"}]}')
data = _reason_json(rubric)
grades = {g.get("i"): g for g in (data.get("grades") or []) if isinstance(g, dict)} if isinstance(data, dict) else {}

print("[3/3] report\n", flush=True)
from collections import Counter, defaultdict
by = defaultdict(list)
for i, r in enumerate(rows):
    g = grades.get(i, {})
    by[r["lane"]].append((g.get("grade","?"), r["query"], g.get("why","")))
tally = Counter()
for lane in sorted(by):
    print(f"=== {lane} ===")
    for grade, q, why in by[lane]:
        tally[grade]+=1
        print(f"  [{grade}] \"{q[:95]}\"")
        if why: print(f"        {why}")
    print()
print("GRADE TALLY:", dict(sorted(tally.items())))
json.dump({"rows":[{**r, **grades.get(i,{})} for i,r in enumerate(rows)]},
          open(os.path.join(os.path.dirname(__file__),"query_grades.json"),"w"), indent=2)
watchdog.stop()
