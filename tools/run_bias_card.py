import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from seeker import bias_probe as bp
print("[bias] running matrix: %d models x %d fixtures x 2 conditions" % (len(bp.CANDIDATES), len(bp.FIXTURES)), flush=True)
res = bp.run_lean_card()
path = bp.write_lean_card(res)
print("[bias] wrote", path, flush=True)
