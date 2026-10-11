"""Real-web generality bench: varied public sites, read-only goals, checked on the final page (not on Jev's word).

Run: PYTHONPATH=. uv run --env-file .env python bench/web.py [task ...]
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import time

def tfs_dates(url):
    """The dates Google Flights encodes in its tfs query parameter."""
    import base64
    from urllib.parse import parse_qs, urlparse
    t = parse_qs(urlparse(url).query).get("tfs", [""])[0]
    try:
        return set(re.findall(r"20\d\d-\d\d-\d\d", base64.urlsafe_b64decode(t + "=" * (-len(t) % 4)).decode("latin-1")))
    except ValueError:
        return set()


# name: (start url, goal, values, check(result) -> bool)
TASKS = {
    "wikipedia_fr": ("https://fr.wikipedia.org/", "Search Wikipedia for Marie Curie and open her article.",
                     {"query": "Marie Curie"}, lambda r: r["url"].endswith("/wiki/Marie_Curie")),
    "github": ("https://github.com/", "Search GitHub for the repository browser-use/browser-use and open it.",
               {"query": "browser-use"}, lambda r: re.search(r"github\.com/browser-use/browser-use/?$", r["url"])),
    "imdb": ("https://www.imdb.com/", "Search IMDb for the film Inception and open its title page.",
             {"query": "Inception"}, lambda r: "/title/tt1375666" in r["url"]),
    "hackernews": ("https://news.ycombinator.com/", "Open the comments page of the first story on the front page.",
                   {}, lambda r: "item?id=" in r["url"]),
    "youtube": ("https://www.youtube.com/", "Search YouTube for Alan Turing documentary and show the results.",
                {"query": "Alan Turing documentary"}, lambda r: "search_query=" in r["url"]),
    "maps": ("https://www.google.com/maps", "Search Google Maps for Tour Eiffel, Paris and open the place.",
             {"query": "Tour Eiffel, Paris"}, lambda r: "/place/" in r["url"]),
    "amazon_fr": ("https://www.amazon.fr/", "Search Amazon for clavier mécanique and open the first product of the results.",
                  {"query": "clavier mécanique"}, lambda r: re.search(r"/dp/|/gp/product/", r["url"])),
    "booking": ("https://www.booking.com/index.fr.html",
                "Search stays in Lisbon from November 20 to November 22, 2026 for 2 adults and show the results.",
                {"destination": "Lisbon", "check_in": "November 20, 2026", "check_out": "November 22, 2026", "adults": "2"},
                lambda r: "searchresults" in r["url"] and "checkin=2026-11-20" in r["url"] and
                "checkout=2026-11-22" in r["url"] and "group_adults=2" in r["url"]),
    "service_public": ("https://www.service-public.fr/", "Search service-public.fr for carte grise and open a result page about it.",
                       {"query": "carte grise"}, lambda r: "service-public" in r["url"] and "recherche" not in r["url"]
                       and "grise" in (r["title"] + r["text"]).lower()),
    "meteo": ("https://meteofrance.com/", "Show the weather forecast page for Montpellier.",
              {"city": "Montpellier"}, lambda r: "montpellier" in r["url"].lower()),
    "doctolib": ("https://www.doctolib.fr/", "Search Doctolib for a dermatologue in Montpellier and show the results.",
                 {"specialty": "dermatologue", "place": "Montpellier"},
                 lambda r: "dermatolog" in r["url"] and "montpellier" in r["url"]),
    # Run before booking/airbnb: the profile then remembers other dates, so those tasks must change them.
    "booking_other": ("https://www.booking.com/index.fr.html",
                      "Search stays in Lisbon from December 11 to December 13, 2026 for 1 adult and show the results.",
                      {"destination": "Lisbon", "check_in": "December 11, 2026", "check_out": "December 13, 2026", "adults": "1"},
                      lambda r: "searchresults" in r["url"] and "checkin=2026-12-11" in r["url"] and
                      "checkout=2026-12-13" in r["url"] and "group_adults=1" in r["url"]),
    "airbnb_other": ("https://www.airbnb.fr/", "Search Airbnb stays in Porto from December 11 to December 13, 2026 and show the results.",
                     {"destination": "Porto", "check_in": "December 11, 2026", "check_out": "December 13, 2026"},
                     lambda r: "/s/" in r["url"] and "2026-12-11" in r["url"] and "2026-12-13" in r["url"]),
    "airbnb": ("https://www.airbnb.fr/", "Search Airbnb stays in Porto from November 20 to November 22, 2026 and show the results.",
               {"destination": "Porto", "check_in": "November 20, 2026", "check_out": "November 22, 2026"},
               lambda r: "/s/" in r["url"] and "2026-11-20" in r["url"] and "2026-11-22" in r["url"]),
    "decathlon": ("https://www.decathlon.fr/", "Search Decathlon for tente 2 places and show the results.",
                  {"query": "tente 2 places"}, lambda r: re.search(r"tente", r["url"], re.I)),
    "flights_return": ("https://www.google.com/travel/flights?hl=en",
                       "Find round-trip flights from Paris to Lisbon, departing November 20, 2026 and returning "
                       "November 27, 2026, and show the results.",
                       {"from": "Paris", "to": "Lisbon", "departure_date": "Nov 20, 2026", "return_date": "Nov 27, 2026"},
                       lambda r: "/travel/flights/search" in r["url"] and tfs_dates(r["url"]) >= {"2026-11-20", "2026-11-27"}),
    "wikipedia_en_link": ("https://en.wikipedia.org/wiki/Alan_Turing",
                          "From the Alan Turing article, open the article about the Turing machine.",
                          {}, lambda r: r["url"].endswith("/wiki/Turing_machine")),
}


def main():
    # --arm original --source <checkout>: run the original jev-ultrafast instead of jevnav, on the same tasks.
    argv, arm, source = sys.argv[1:], "fork", None
    if "--arm" in argv:
        i = argv.index("--arm"); arm = argv[i + 1]; del argv[i:i + 2]
    if "--source" in argv:
        i = argv.index("--source"); source = argv[i + 1]; del argv[i:i + 2]
    names = argv or list(TASKS)
    ok_count = 0
    for name in names:
        url, goal, values, check = TASKS[name]
        cmd = [sys.executable, "-m", "jev_ultrafast.nav"] if arm == "fork" else \
            ["uv", "run", "--quiet", "--project", source, "python", str(Path(__file__).with_name("original_arm.py")),
             "--source", source]
        cmd += ["--url", url, "--goal", goal, "--budget", "90", "--text-chars", "3000"]
        if values:
            cmd += ["--values", json.dumps(values)]
        t = time.perf_counter()
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        try:
            r = json.loads(out)
        except ValueError:
            r = {"status": "crash", "url": "", "title": "", "text": out[-300:]}
        ok = bool(r["status"] == "done" and r.get("url") is not None and check({"url": r.get("url") or "", "title": r.get("title") or "",
                                                     "text": r.get("text") or ""}))
        ok_count += ok
        print(json.dumps({"arm": arm, "task": name, "ok": ok, "status": r["status"], "s": round(time.perf_counter() - t, 1),
                          "steps": r.get("steps"), "url": (r.get("url") or "")[:90], "actions": (r.get("actions") or [])[-6:],
                          **{k: r[k] for k in ("action", "field", "reason", "error") if k in r}}, ensure_ascii=False), flush=True)
        if r.get("target"):
            subprocess.run([sys.executable, "-c", "from browser_harness.helpers import cdp; "
                            f"cdp('Target.closeTarget', targetId='{r['target']}')"], capture_output=True)
    print(f"{ok_count}/{len(names)} verified")


if __name__ == "__main__":
    main()
