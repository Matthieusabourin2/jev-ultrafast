"""Original jev-ultrafast (1231850), with its text model replaced by an instant answer (an advantage to it)."""
import json, sys, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from jev_ultrafast import agent as agent_mod, browser as bmod, model as mmod
import os
if os.environ.get('PROFILE'):
    import profile as P; P.install(bmod)
from common import URL, GOAL, verify
def instant(context):
    label = (context["field"]["label"] or "").lower()
    text = "Zurich" if "from" in label else "London" if "to" in label else "Nov 20, 2026"
    return text, {"model": "instant", "latency_ms": 0, "usage": {}}
agent_mod.field_text = instant
n = {"jev": 0, "jev_s": 0.0}
orig = mmod.post_json
def counted(*a, **k):
    t = time.perf_counter(); r = orig(*a, **k); n["jev"] += 1; n["jev_s"] += time.perf_counter() - t; return r
mmod.post_json = counted
a = agent_mod.Agent(URL, GOAL)
t0 = time.perf_counter(); err = None
try:
    for s in a.run(): pass
except Exception as e:
    err = f"{type(e).__name__}: {e}"
s = a.snapshot(); a.browser.evaluate("scrollTo(0,0)"); time.sleep(0.3); ok, checks = verify(a.browser.observe(screenshot=False))
print(json.dumps({"arm": "original", "status": s["status"], "ok": ok, "elapsed_s": round(s["elapsed_ms"] / 1000, 2),
                  "wall_after_load_s": round(time.perf_counter() - t0, 2), "steps": len(s["history"]),
                  "jev_calls": n["jev"], "jev_s": round(n["jev_s"], 2), "error": err,
                  "actions": [h["action"][:40] for h in s["history"]],
                  "failed": [k for k, v in checks.items() if not v]}, ensure_ascii=False), flush=True)
a.close()
