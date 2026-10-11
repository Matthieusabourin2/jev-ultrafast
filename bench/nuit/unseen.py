"""Sites never used to tune jevnav. Measured only, never debugged directly: a failure is first reproduced as a local
hard case. Frozen on 11 October 2026, before the night's first experiment.
"""
import re

# name: (start url, goal, values, check(result) -> bool)
TASKS = {
    "stackoverflow": ("https://stackoverflow.com/questions", "Search Stack Overflow for python asyncio gather and show the results.",
                      {"query": "python asyncio gather"}, lambda r: "search?q=" in r["url"] or "/search" in r["url"]),
    "pypi": ("https://pypi.org/", "Search PyPI for httpx and open the httpx project page.",
             {"query": "httpx"}, lambda r: re.search(r"pypi\.org/project/httpx/?$", r["url"])),
    "npmjs": ("https://www.npmjs.com/", "Search npm for react and open the react package page.",
              {"query": "react"}, lambda r: re.search(r"npmjs\.com/package/react/?$", r["url"])),
    "wikipedia_de": ("https://de.wikipedia.org/", "Search Wikipedia for Albert Einstein and open his article.",
                     {"query": "Albert Einstein"}, lambda r: r["url"].endswith("/wiki/Albert_Einstein")),
    "allocine": ("https://www.allocine.fr/", "Search Allociné for the film Inception and open its film page.",
                 {"query": "Inception"}, lambda r: "fichefilm" in r["url"] and "143692" in r["url"]),
    "marmiton": ("https://www.marmiton.org/", "Search Marmiton for ratatouille recipes and show the results.",
                 {"query": "ratatouille"}, lambda r: "ratatouille" in r["url"].lower()),
    "fnac": ("https://www.fnac.com/", "Search Fnac for kindle and show the results.",
             {"query": "kindle"}, lambda r: "kindle" in r["url"].lower()),
    "ikea": ("https://www.ikea.com/fr/fr/", "Search IKEA for billy bookcase and show the results.",
             {"query": "billy"}, lambda r: "billy" in r["url"].lower()),
    "leroymerlin": ("https://www.leroymerlin.fr/", "Search Leroy Merlin for perceuse and show the results.",
                    {"query": "perceuse"}, lambda r: "perceuse" in r["url"].lower()),
    "openstreetmap": ("https://www.openstreetmap.org/", "Search OpenStreetMap for Montpellier and show the results.",
                      {"query": "Montpellier"}, lambda r: "query=Montpellier" in r["url"] or "/relation/" in r["url"]),
    "lemonde": ("https://www.lemonde.fr/", "Open the International section of Le Monde.",
                {}, lambda r: "/international/" in r["url"]),
    "pagesjaunes": ("https://www.pagesjaunes.fr/", "Search PagesJaunes for boulangerie in Montpellier and show the results.",
                    {"what": "boulangerie", "where": "Montpellier"},
                    lambda r: "boulangerie" in r["url"].lower() and "montpellier" in r["url"].lower()),
    "ameli": ("https://www.ameli.fr/", "Search ameli.fr for carte vitale and show the results.",
              {"query": "carte vitale"}, lambda r: "carte" in r["url"].lower() and "vitale" in r["url"].lower()),
    "mdn": ("https://developer.mozilla.org/en-US/", "Search MDN for Array map and open the Array.prototype.map() page.",
            {"query": "Array map"}, lambda r: r["url"].rstrip("/").endswith("/Global_Objects/Array/map")),
    "larousse": ("https://www.larousse.fr/", "Look up the word ordinateur in the Larousse French dictionary and open its definition.",
                 {"word": "ordinateur"}, lambda r: "dictionnaires/francais/ordinateur" in r["url"]),
    "trainline": ("https://www.thetrainline.com/fr", "Search trains from Paris to Lyon on November 20, 2026 for one adult and show the results.",
                  {"from": "Paris", "to": "Lyon", "date": "November 20, 2026"},
                  lambda r: "2026-11-20" in r["url"] and ("result" in r["url"] or "search" in r["url"])),
}
