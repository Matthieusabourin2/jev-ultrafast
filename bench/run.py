"""Benchmark jevnav on the user's own browser profile. Each run goes through the real CLI.

Run: PYTHONPATH=. uv run --env-file .env python bench/run.py [--runs 3]
Writes bench/results/<timestamp>.json and prints a Markdown table.
"""

import argparse
import base64
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from browser_harness.helpers import cdp
from jev_ultrafast.browser import Browser


def flights_ok(page):
    """Independent route/date checks on the final Google Flights page (adapted from examples/flights.py)."""
    parsed = urlparse(page["url"])
    encoded = parse_qs(parsed.query).get("tfs", [""])[0]
    try:
        year = b"2026-11-20" in base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except ValueError:
        year = False
    values = {a["label"].strip(): a.get("value") for a in page["actions"]}
    flights = [a["label"] for a in page["actions"] if "Select flight" in a["label"]]
    return all([
        parsed.path == "/travel/flights/search",
        values.get("Change ticket type. One way") == "One way",
        values.get("Where from?") == "Zürich",
        values.get("Where to?") == "London",
        values.get("Departure") == "Fri, Nov 20",
        year or "departing 2026-11-20" in page["text"],
        bool(flights) and all("Friday, November 20" in f for f in flights),
    ])


TASKS = {
    "wikipedia": dict(
        url="https://en.wikipedia.org/wiki/Main_Page",
        goal="Search Wikipedia for Alan Turing and open his article",
        values={"query": "Alan Turing"},
        check=lambda p: p["url"].endswith("/wiki/Alan_Turing"),
    ),
    "flights": dict(
        url="https://www.google.com/travel/flights?hl=en",
        goal="Find one-way flights from Zurich to London on November 20, 2026, for one adult in economy. "
             "Stop when matching flight options are visible. Do not select or book a flight.",
        values={"from": "Zurich", "to": "London", "departure_date": "Nov 20, 2026"},
        check=flights_ok,
    ),
    "link": dict(
        url="https://the-internet.herokuapp.com/",
        goal="Open the Dynamic Controls page.",
        values={},
        check=lambda p: p["url"].endswith("/dynamic_controls"),
    ),
    "async_button": dict(
        url="https://the-internet.herokuapp.com/dynamic_controls",
        goal="Enable the text input and wait until the page says it is enabled.",
        values={},
        check=lambda p: "It's enabled!" in p["text"],
    ),
}


def run_once(task):
    cmd = [sys.executable, "-m", "jev_ultrafast.nav", "--url", task["url"], "--goal", task["goal"], "--text-chars", "0"]
    if task["values"]:
        cmd += ["--values", json.dumps(task["values"])]
    result = json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)
    verified = False
    if result.get("target"):
        browser = Browser(None, target=result["target"])
        verified = bool(task["check"](browser.observe(screenshot=False)))
        cdp("Target.closeTarget", targetId=result["target"])
    return {k: result.get(k) for k in ("status", "nav_s", "elapsed_s")} | {"actions": len(result.get("actions") or []),
                                                                         "verified": verified}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--tasks", nargs="*", default=list(TASKS))
    args = parser.parse_args()
    results = {name: [run_once(TASKS[name]) for _ in range(args.runs)] for name in args.tasks}
    out = Path(__file__).with_name("results") / time.strftime("%Y-%m-%d-%H%M.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print("| Task | Verified | Navigation (s) | Total with first load (s) | Actions |\n|---|---|---|---|---|")
    for name, runs in results.items():
        nav = [r["nav_s"] for r in runs if r["nav_s"] is not None]
        total = [r["elapsed_s"] for r in runs if r["elapsed_s"] is not None]
        ok = sum(r["verified"] for r in runs)
        span = lambda xs: f"{min(xs):.1f} to {max(xs):.1f} (median {statistics.median(xs):.1f})" if xs else "n/a"
        print(f"| {name} | {ok}/{len(runs)} | {span(nav)} | {span(total)} | {'/'.join(str(r['actions']) for r in runs)} |")
    print(f"\nRaw results: {out}")


if __name__ == "__main__":
    main()
