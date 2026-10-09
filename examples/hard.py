"""End-to-end hard cases from real use (claude.ai menus, URSSAF dropdowns), on local pages, in the real browser.

Each page stores what the user would see as done in window.__result. Run:
PYTHONPATH=. uv run --env-file .env python examples/hard.py [case ...]
"""

import functools
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

from browser_harness.helpers import cdp
from jev_ultrafast.browser import Browser

ROOT = Path(__file__).with_name("hard")
CASES = {
    # Five rows, each with an icon-only "…" button and a menu rendered in a portal (claude.ai projects list).
    "row_menu": ("Rename the project « Veille IA »: open its options menu and choose Renommer.", {}, "rename:Veille IA"),
    # An icon "+" button known only by its tooltip, then a dialog with two fields (claude.ai custom connector).
    "add_dialog": ("Add a custom connector named gbrain with the server URL https://brain.example.com/mcp.",
                   {"name": "gbrain", "url": "https://brain.example.com/mcp"}, "gbrain|https://brain.example.com/mcp"),
    # Native selects, one of them with 400 options, then a button below them (URSSAF address form).
    "long_select": ("Choose France as the country and Montpellier as the commune, then click Continuer.",
                    {"country": "France", "commune": "Montpellier"}, "France|Montpellier"),
    # A custom combobox opening a listbox of accounts (URSSAF account switcher).
    "custom_listbox": ("Switch to the Travailleur indépendant account and validate.", {}, "Travailleur indépendant",
                       "Valider"),
    # Clickable cards that are plain divs, with no role (account chooser).
    "div_cards": ("Open the travailleur indépendant account.", {}, "ti"),
    # A reversible edit saved with "Enregistrer" (claude.ai project instructions).
    # A business form on a signed-in site: SIRET, APE and commune codes are not credentials (URSSAF).
    "business_form": ("Fill the company form: SIRET 12345678900012, code APE 6202A, code commune 34172, contact email "
                      "contact@example.com, then go to the next step.",
                      {"siret": "12345678900012", "ape": "6202A", "commune": "34172", "email": "contact@example.com"},
                      "12345678900012|6202A|34172|contact@example.com"),
    # Sharing with an email address is not a sign-in (Google Drive).
    "share_email": ("Share the report with sami@example.com as Éditeur.", {"recipient": "sami@example.com"},
                    "sami@example.com|Éditeur", "Partager"),
    # A contenteditable editor (claude.ai project instructions, ProseMirror).
    "rich_editor": ("Write « Veille IA chaque lundi » in the instructions and save.", {"instructions": "Veille IA chaque lundi"},
                    "Veille IA chaque lundi"),
    # Row buttons that only appear on hover (claude.ai conversation list).
    "hover_rows": ("Open the options of the conversation « Veille IA lundi ».", {}, "menu:Veille IA lundi"),
    # The page itself does not scroll; the list scrolls inside <main> (claude.ai settings).
    "inner_scroll": ("Click Configurer on the gbrain connector.", {}, "configure:gbrain"),
    # A step progress bar is not a loading state (claude.ai scheduled task form).
    "wizard": ("Create a scheduled task named « Veille du lundi » that runs every Monday.", {"name": "Veille du lundi"},
               "Veille du lundi|lundi"),
    # The wanted option starts below the edge of a short scrolling list; a logout button sits nearby (URSSAF).
    "clipped_listbox": ("Select the Travailleur indépendant account, then open its space.", {}, "Travailleur indépendant"),
    # A form in a modal that scrolls on its own, with a custom day list and the save button below its edge (claude.ai).
    "modal_scroll": ("Create a new scheduled task named « Veille IA » that runs on lundi, and save it.", {"name": "Veille IA"},
                     "Veille IA|lundi"),
    "settings_save": ("Replace the project instructions with « Veille IA chaque lundi » and save them.",
                      {"instructions": "Veille IA chaque lundi"}, "Veille IA chaque lundi"),
}


def main():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    failures = 0
    for case in sys.argv[1:] or CASES:
        goal, values, expected, *confirm = CASES[case]
        url = f"http://127.0.0.1:{server.server_port}/{case}.html"
        cmd = [sys.executable, "-m", "jev_ultrafast.nav", "--url", url, "--goal", goal, "--budget", "60", "--text-chars", "0"]
        if values:
            cmd += ["--values", json.dumps(values)]
        if confirm:  # the user already agreed to this one irreversible click
            cmd += ["--confirm", confirm[0]]
        result = json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)
        got = None
        if result.get("target"):
            got = Browser(None, target=result["target"]).evaluate("window.__result ?? null")
            cdp("Target.closeTarget", targetId=result["target"])
        ok = got == expected
        failures += not ok
        print(json.dumps({"case": case, "ok": ok, "status": result["status"], "got": got, "s": result.get("elapsed_s"),
                          "actions": result.get("actions"), **{k: result[k] for k in ("action", "field", "reason", "error")
                                                                 if k in result}}, ensure_ascii=False), flush=True)
    server.shutdown()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
