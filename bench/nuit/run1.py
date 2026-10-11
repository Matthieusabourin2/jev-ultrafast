"""Run one task with the jevnav checkout at --src, check the final page, print one JSON line.

Tasks: any name of bench/web.py, any hard case (hard:<case>), flights (Google Flights one way, the duel task),
or any name of bench/nuit/unseen.py (unseen:<name>).
Run: uv run --env-file .env python bench/nuit/run1.py --src <checkout> <task>
"""
import functools
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(REPO), str(REPO / "bench"), str(REPO / "bench" / "duel"), str(REPO / "examples"), str(HERE)]


def run(src, task):
    from browser_harness.helpers import cdp
    from jev_ultrafast.browser import Browser
    server = None
    page_check = None
    extra = []
    if task.startswith("hard:"):
        import hard
        case = task[5:]
        goal, values, expected, *confirm = hard.CASES[case]
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=hard.ROOT)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/{case}.html"
        if confirm:
            extra = ["--confirm", confirm[0]]
        page_check = lambda b, r: b.evaluate("window.__result ?? null") == expected
        budget, chars = "60", "0"
    elif task == "flights":
        import common
        url, goal, values = common.URL, common.GOAL, common.VALUES
        page_check = lambda b, r: common.verify(b.observe(screenshot=False))[0]
        budget, chars = "90", "0"
    else:
        if task.startswith("perso:"):
            import perso
            url, goal, values, check = perso.TASKS[task[6:]]
            extra = ["--login-wait", "5"]  # a sign-in page means the session expired: stop, never type
        elif task.startswith("unseen2:"):
            import unseen2
            url, goal, values, check = unseen2.TASKS[task[8:]]
        elif task.startswith("unseen:"):
            import unseen
            url, goal, values, check = unseen.TASKS[task[7:]]
        else:
            import web
            url, goal, values, check = web.TASKS[task]
        budget, chars = "90", "3000"
    cmd = [sys.executable, "-m", "jev_ultrafast.nav", "--url", url, "--goal", goal, "--budget", budget,
           "--text-chars", chars, *extra]
    if values:
        cmd += ["--values", json.dumps(values)]
    env = os.environ | {"PYTHONPATH": str(src)}
    t = time.perf_counter()
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=src, env=env).stdout
    wall = time.perf_counter() - t
    try:
        r = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        r = {"status": "crash", "error": out[-300:]}
    ok = False
    if r.get("status") == "done":
        if page_check and r.get("target"):
            try:
                ok = bool(page_check(Browser(None, target=r["target"]), r))
            except Exception as e:  # a closed tab or a navigation mid-check is a failure, not a crash
                r["error"] = f"check: {e}"
        elif not page_check:
            ok = bool(check({"url": r.get("url") or "", "title": r.get("title") or "", "text": r.get("text") or ""}))
    if r.get("target"):
        try:
            cdp("Target.closeTarget", targetId=r["target"])
        except Exception:
            pass
    if server:
        server.shutdown()
    return {"task": task, "ok": ok, "status": r.get("status"), "s": round(wall, 2), "elapsed_s": r.get("elapsed_s"),
            "steps": r.get("steps"), "url": (r.get("url") or "")[:100], "actions": (r.get("actions") or [])[-8:],
            **{k: r[k] for k in ("action", "field", "reason", "error") if k in r}}


if __name__ == "__main__":
    argv = sys.argv[1:]
    i = argv.index("--src"); src = Path(argv[i + 1]).resolve(); del argv[i:i + 2]
    for task in argv:
        print(json.dumps(run(src, task), ensure_ascii=False), flush=True)
