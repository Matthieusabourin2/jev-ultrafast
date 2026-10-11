"""Run one jevnav task in-process and save every Jev request with its answer (bench/nuit/requests/<name>.jsonl),
to replay variants of the request offline. Usage: record.py NAME <jevnav args>"""
import json, sys
from pathlib import Path
from jev_ultrafast import agent

name, sys.argv = sys.argv[1], ["jevnav", *sys.argv[2:]]
out = Path(__file__).with_name("requests"); out.mkdir(exist_ok=True)
f = open(out / f"{name}.jsonl", "a")
real = agent.choose


def choose(state, goal, history):
    d = real(state, goal, history)
    f.write(json.dumps({"request": d["request"], "choice": d["choice"], "operation": d["operation"],
                        "target": d["target"], "latency_ms": d["latency_ms"], "usage": d["usage"]}) + "\n"); f.flush()
    return d


agent.choose = choose
from jev_ultrafast import nav  # noqa: E402
try:
    nav.main()
except SystemExit:
    pass
