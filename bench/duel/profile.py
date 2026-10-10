"""Imported by an arm when PROFILE=1: time every CDP call by method (and evaluate by expression head), and sleeps."""
import atexit, json, sys, time
from collections import defaultdict
T = defaultdict(lambda: [0, 0.0])
def install(bmod):
    raw = bmod.cdp
    def timed(method, *a, **k):
        t = time.perf_counter(); r = raw(method, *a, **k); dt = time.perf_counter() - t
        key = method
        if method == "Runtime.evaluate":
            e = k.get("expression", "")
            key += " " + ("SETTLE" if "MutationObserver" in e and len(e) < 900 else "READ" if "__jevFast" in e and len(e) > 5000
                          else "AFTER_INPUT" if "requestAnimationFrame(ready)" in e else e[:40].replace("\n", " "))
        T[key][0] += 1; T[key][1] += dt; return r
    bmod.cdp = timed
    rs = time.sleep
    def sl(x): T["sleep"][0] += 1; T["sleep"][1] += x; rs(x)
    time.sleep = sl
    atexit.register(lambda: print("PROFILE " + json.dumps({k: [v[0], round(v[1], 2)] for k, v in sorted(T.items(), key=lambda kv: -kv[1][1])}), file=sys.stderr))
