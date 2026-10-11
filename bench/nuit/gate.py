"""Non-regression gate: every task here must pass. A failure is rerun once; a pass on the rerun is logged as flaky.

Run: uv run --env-file .env python bench/nuit/gate.py --src <checkout> --label <name> [--quick]
--quick skips the real sites (unit tests, hard cases and guards only).
"""
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]), str(HERE), str(HERE.parents[1] / "examples")]
import hard  # noqa: E402
import run1  # noqa: E402

WEB = ["wikipedia_fr", "github", "imdb", "hackernews", "youtube", "amazon_fr", "service_public", "meteo", "doctolib",
       "decathlon", "flights_return", "wikipedia_en_link", "flights", "maps", "airbnb_other", "airbnb", "booking_other", "booking"]
# Failing before the night with other dates in the profile: run and reported, not required (a known gap, not a regression).
FRONTIER = []  # Booking joined the required set after e35 (month navigation): 3 passes out of 3
EXTRA = [t for t in os.environ.get("GATE_EXTRA", "").split(",") if t]  # tasks won during the night join the gate


def main():
    argv = sys.argv[1:]
    src = Path(argv[argv.index("--src") + 1]).resolve()
    label = argv[argv.index("--label") + 1]
    quick = "--quick" in argv
    log = HERE / "runs" / f"{label}.jsonl"
    log.parent.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    unit = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=src, capture_output=True, text=True,
                          env=os.environ | {"PYTHONPATH": str(src)})
    guards = subprocess.run([sys.executable, "examples/guards.py"], cwd=src, capture_output=True, text=True,
                            env=os.environ | {"PYTHONPATH": str(src)})
    tasks = [f"hard:{c}" for c in hard.CASES] + ([] if quick else WEB + EXTRA + FRONTIER)
    rows, fails, flaky, frontier = [], [], [], []
    with log.open("w") as f:
        for task in tasks:
            r = run1.run(src, task)
            if not r["ok"]:
                r2 = run1.run(src, task)
                r["retry"] = r2
                (flaky if r2["ok"] else frontier if task in FRONTIER else fails).append(task)
            rows.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
    unit_ok = unit.returncode == 0
    guards_ok = guards.returncode == 0
    times = {r["task"]: r["s"] for r in rows if r["ok"]}
    web_times = [s for t, s in times.items() if not t.startswith("hard:")]
    hard_times = [s for t, s in times.items() if t.startswith("hard:")]
    summary = {"label": label, "pass": unit_ok and guards_ok and not fails, "unit": unit.stdout.strip().splitlines()[-1:],
               "guards_ok": guards_ok, "fails": fails, "flaky": flaky, "frontier_fails": frontier, "n": len(tasks),
               "web_sum_s": round(sum(web_times), 1), "hard_sum_s": round(sum(hard_times), 1),
               "web_median_s": round(statistics.median(web_times), 2) if web_times else None,
               "steps": sum(r.get("steps") or 0 for r in rows), "minutes": round((time.perf_counter() - t0) / 60, 1)}
    if not guards_ok:
        summary["guards_out"] = guards.stdout[-800:]
    print(json.dumps(summary, ensure_ascii=False))
    with (HERE / "gates.jsonl").open("a") as f:
        f.write(json.dumps(summary | {"times": times}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
