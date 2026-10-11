"""Tableau Markdown des expériences de la nuit, depuis ledger.jsonl (une ligne par expérience)."""
import json
from pathlib import Path

KIND = {  # comment chaque expérience a été jugée
    "rejeu": {"e9-text3000", "e10-text1500", "e11-notext", "e12-label60", "e13-noelements", "e14-hist5",
               "e24", "e29", "e30", "e31", "e32", "e38", "e39", "e40", "e41", "e51"},
    "nul": {"e42"},
    "outil": {"e00", "e03"},
}
rows = [json.loads(l) for l in Path(__file__).with_name("ledger.jsonl").read_text().splitlines() if l.strip()]
print("| # | Expérience | Verdict | Mesure |\n|---|---|---|---|")
for r in rows:
    if r["verdict"] == "NOTE":
        continue
    kind = next((k for k, ids in KIND.items() if r["id"] in ids), "bout en bout")
    verdict = {"KEPT": "gardée", "DROPPED": "rejetée"}[r["verdict"]]
    print(f"| {r['id']} | {r['title']} | {verdict} ({kind}) | {r.get('measure', '').replace('|', '/')} |")
