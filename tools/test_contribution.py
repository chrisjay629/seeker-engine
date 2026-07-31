"""Does the contribution lane actually ADD anything to the v19 map? One real call."""
import sys, json
sys.path.insert(0, "src")
from seeker import contribute as cb, synthesis as syn, identity as idm
from seeker.memory.memory_map import MemoryMap

BR = "missing-scientists-v19"
Q = ("The 2026 'missing scientists' case: for EACH named individual, verified status and documented "
     "cause — and is there a genuine coordinated pattern or a coincidental cluster of unrelated cases?")
ROSTER = ["William Neil McCasland","Monica Jacinto Reza","Anthony Chavez","Steven Garcia",
          "Carl Grillmair","Nuno Loureiro","Jason Thomas","Melissa Casias","Frank Maiwald",
          "Michael David Hicks","Matthew James Sullivan","Amy Eskridge","Joshua LeBlanc"]
mm = MemoryMap()
b = syn.gather_findings(Q, branch_id=BR, top_k=500, mm=mm)
existing = [f["claim"] for lab in b for f in b[lab]]
print(f"map holds {len(existing)} claims; asking what Perplexity can add...", flush=True)
cards = idm.build_cards(Q, ROSTER, branch_id=BR, mm=mm)
res = cb.contribute(Q, ROSTER, existing, cards=cards, branch_id=BR)
print(cb.format_contribution(res), flush=True)
json.dump({k: (v if k != "findings" else [f.to_dict() for f in v]) for k, v in res.items()},
          open("runs/contribution_test.json", "w"), indent=2, default=str)
print(">>> CONTRIBUTION TEST DONE", flush=True)
