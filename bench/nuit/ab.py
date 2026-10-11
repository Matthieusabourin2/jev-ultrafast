"""A/B duel between two jevnav checkouts on the same tasks, in alternated pairs.

Run: uv run --env-file .env python bench/nuit/ab.py --a <base checkout> --b <candidate checkout> --pairs 3 task [task ...]
Prints one JSON line per run and a summary: success per arm, median wall time per task, pairs won by B, sign test.
"""
import json
import statistics
import sys
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run1  # noqa: E402


def sign_p(wins, n):
    """One-sided sign test: chance of B winning at least `wins` of `n` pairs if both arms were equal."""
    return sum(comb(n, k) for k in range(wins, n + 1)) / 2 ** n if n else 1.0


def main():
    argv = sys.argv[1:]
    def opt(name, default=None):
        if name in argv:
            i = argv.index(name); v = argv[i + 1]; del argv[i:i + 2]; return v
        return default
    a, b = Path(opt("--a")).resolve(), Path(opt("--b")).resolve()
    pairs = int(opt("--pairs", "3"))
    out = opt("--out")
    res = {"A": {}, "B": {}}
    lines = []
    for i in range(pairs):
        for task in argv:
            order = [("A", a), ("B", b)] if i % 2 == 0 else [("B", b), ("A", a)]
            for arm, src in order:
                r = run1.run(src, task) | {"arm": arm, "pair": i}
                res[arm].setdefault(task, []).append(r)
                lines.append(r)
                print(json.dumps(r, ensure_ascii=False), flush=True)
    summary = {"tasks": {}, "ok_A": 0, "ok_B": 0, "n": pairs * len(argv), "wins_B": 0, "pairs": 0}
    for task in argv:
        ra, rb = res["A"][task], res["B"][task]
        summary["ok_A"] += sum(r["ok"] for r in ra)
        summary["ok_B"] += sum(r["ok"] for r in rb)
        both = [(x["s"], y["s"]) for x, y in zip(ra, rb) if x["ok"] and y["ok"]]
        wins = sum(y < x for x, y in both)
        summary["wins_B"] += wins
        summary["pairs"] += len(both)
        summary["tasks"][task] = {
            "ok": [sum(r["ok"] for r in ra), sum(r["ok"] for r in rb)],
            "median": [round(statistics.median([r["s"] for r in ra if r["ok"]]), 2) if any(r["ok"] for r in ra) else None,
                       round(statistics.median([r["s"] for r in rb if r["ok"]]), 2) if any(r["ok"] for r in rb) else None],
            "steps": [statistics.median([r.get("steps") or 0 for r in ra]), statistics.median([r.get("steps") or 0 for r in rb])],
            "wins_B": f"{wins}/{len(both)}"}
    ta = [x for t in summary["tasks"].values() if None not in t["median"] for x in [t["median"][0]]]
    tb = [x for t in summary["tasks"].values() if None not in t["median"] for x in [t["median"][1]]]
    summary["sum_median"] = [round(sum(ta), 2), round(sum(tb), 2)]
    summary["sign_p"] = round(sign_p(summary["wins_B"], summary["pairs"]), 3)
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    if out:
        Path(out).write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\nSUMMARY " +
                             json.dumps(summary, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
