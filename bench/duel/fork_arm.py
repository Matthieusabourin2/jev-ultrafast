"""Our fork (jevnav), same task: values supplied by the caller, as jevnav is used."""
import contextlib, io, json, sys, time
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
from jev_ultrafast import nav, model as mmod
import os
if os.environ.get('PROFILE'):
    import profile as P; from jev_ultrafast import browser as bmod; P.install(bmod)
from jev_ultrafast.browser import Browser
from common import URL, GOAL, VALUES, verify
n = {"jev": 0, "jev_s": 0.0}
orig = mmod.CLIENT.post
def counted(*a, **k):
    t = time.perf_counter(); r = orig(*a, **k); n["jev"] += 1; n["jev_s"] += time.perf_counter() - t; return r
mmod.CLIENT.post = counted
sys.argv = ["jevnav", "--url", URL, "--goal", GOAL, "--values", json.dumps(VALUES), "--text-chars", "0"]
out = io.StringIO()
with contextlib.redirect_stdout(out):
    try: nav.main()
    except SystemExit: pass
r = json.loads(out.getvalue().strip().splitlines()[-1])
b = Browser(None, target=r["target"])
b.evaluate("scrollTo(0,0)"); time.sleep(0.3); fp = b.observe(screenshot=False); ok, checks = verify(fp); b.close()
if not ok: print("FLIGHTS", [a["label"][:140] for a in fp["actions"] if "flight" in a["label"].lower()][:4], fp["url"][:80], file=sys.stderr)
print(json.dumps({"arm": "fork", "status": r["status"], "ok": ok, "elapsed_s": r.get("nav_s"), "wall_total_s": r.get("elapsed_s"),
                  "steps": len(r.get("actions", [])), "jev_calls": n["jev"], "jev_s": round(n["jev_s"], 2),
                  "actions": [x[:40] for x in r.get("actions", [])], "failed": [k for k, v in checks.items() if not v]},
                 ensure_ascii=False), flush=True)
