"""Duel jevnav contre jev-ultrafast d'origine sur Google Flights : même URL, même objectif, même contrôle de la page.

Lancer (une paire ; alterner les passages) :
  git worktree add /tmp/upstream upstream/main && (cd /tmp/upstream && uv sync)
  (cd /tmp/upstream && uv run --env-file <repo>/.env python <repo>/bench/duel/upstream_arm.py /tmp/upstream <repo>/bench/duel)
  PYTHONPATH=. uv run --env-file .env python bench/duel/fork_arm.py . bench/duel
PROFILE=1 ajoute le temps par appel CDP et par pause, sur la sortie d'erreur.
"""
import base64
from urllib.parse import parse_qs, urlparse

URL = "https://www.google.com/travel/flights?hl=en"
GOAL = ("Find one-way flights from Zurich to London on November 20, 2026, for one adult in economy. "
        "Stop when matching flight options are visible. Do not select or book a flight.")
VALUES = {"from": "Zurich", "to": "London", "departure_date": "Nov 20, 2026"}


def verify(page):
    parsed = urlparse(page["url"])
    enc = parse_qs(parsed.query).get("tfs", [""])[0]
    try:
        date_ok = b"2026-11-20" in base64.urlsafe_b64decode(enc + "=" * (-len(enc) % 4))
    except ValueError:
        date_ok = False
    values = {a["label"].strip(): a.get("value") for a in page["actions"]}
    flights = [a["label"] for a in page["actions"] if "Select flight" in a["label"]]
    checks = {"search_page": parsed.path == "/travel/flights/search",
              "one_way": any(k.startswith("Change ticket type") and v == "One way" for k, v in values.items()),
              "origin": values.get("Where from?") in ("Zürich", "Zurich"),
              "destination": values.get("Where to?") == "London",
              "date": date_ok, "results": bool(flights) and all("November 20" in f for f in flights)}
    return all(checks.values()), checks
