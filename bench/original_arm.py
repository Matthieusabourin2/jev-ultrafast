"""Run the original jev-ultrafast on one task, printing a jevnav-shaped JSON result (for bench/web.py --arm original).

The original writes field text with a second model (DeepSeek by default). Here it gets jevnav's value chooser
instead (Jev picks among the supplied values), so both arms type the same values at the same cost."""

import argparse
import json
import sys
import time

p = argparse.ArgumentParser()
p.add_argument("--source", required=True, help="checkout of the original repository")
p.add_argument("--url", required=True)
p.add_argument("--goal", required=True)
p.add_argument("--values", default="{}")
p.add_argument("--budget", type=float, default=90)
p.add_argument("--text-chars", type=int, default=3000)
args, _ = p.parse_known_args()
# Ours first, for the value choice only; then the original's package under the same name.
sys.path.insert(0, __file__.rsplit("/bench/", 1)[0])
from jev_ultrafast.nav import Stop, value_chooser  # noqa: E402

for name in [m for m in sys.modules if m == "jev_ultrafast" or m.startswith("jev_ultrafast.")]:
    del sys.modules[name]
sys.path[0] = args.source
from jev_ultrafast import agent as original  # noqa: E402

chooser = value_chooser(json.loads(args.values), [])


def field_text(context):
    try:
        return chooser(context)
    except Stop:
        raise ValueError("no supplied value fits this field") from None


original.field_text = field_text
started = time.perf_counter()
agent = original.Agent(args.url, args.goal)
status, error = "in_progress", None
try:
    for state in agent.run():
        if time.perf_counter() - started > args.budget:
            break
    status = agent.state["status"] if agent.state["status"] in {"done", "blocked"} else "in_progress"
except Exception as e:  # noqa: BLE001
    status, error = "error", f"{type(e).__name__}: {e}"
s = agent.snapshot()
page = agent.state["page"]
print(json.dumps({"status": status, "error": error, "elapsed_s": round(time.perf_counter() - started, 2),
                  "nav_s": round(s["elapsed_ms"] / 1000, 2), "steps": len(s["history"]),
                  "actions": [h["action"] for h in s["history"]], "url": page["url"], "title": page["title"],
                  "text": page["text"][:args.text_chars], "target": agent.browser.target}, ensure_ascii=False))
