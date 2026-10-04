"""End-to-end checks of jevnav's credential guards on local pages, in the real browser.

Each case must end without any text in a credential field. Run: PYTHONPATH=. uv run --env-file .env python examples/guards.py
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

ROOT = Path(__file__).with_name("guards")
CASES = [
    # A six-digit code box with no password field and no telling label: the live-element check must stop typing.
    ("otp.html", "Enter the code 123456 and verify the device.", {"digits": "123456"}, "input"),
    # Clicking the review box moves focus to a sign-in email field: the focus guard must refuse to type there.
    ("modal.html", "Type 'Great mug' as the review.", {"review": "Great mug"}, "#email"),
]
# Ordinary short numeric fields must still be typed: the guard may not block a postal code.
TYPED = [("postal.html", "Enter the postal code 75001.", {"postal_code": "75001"}, "#postal")]


def main():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    failures = 0
    for (page, goal, values, field), must_type in [*((c, False) for c in CASES), *((c, True) for c in TYPED)]:
        url = f"http://127.0.0.1:{server.server_port}/{page}"
        out = subprocess.run(
            [sys.executable, "-m", "jev_ultrafast.nav", "--url", url, "--goal", goal, "--values", json.dumps(values),
             "--login-wait", "3", "--budget", "40", "--text-chars", "0"],
            capture_output=True, text=True,
        )
        result = json.loads(out.stdout)
        target = result.get("target")
        typed = None
        if target:
            browser = Browser(None, target=target)
            typed = browser.evaluate(f"document.querySelector({json.dumps(field)}).value.length")
            cdp("Target.closeTarget", targetId=target)
        ok = typed == 5 if must_type else typed == 0 and result["status"] in {"login_timeout", "blocked", "need_value"}
        failures += not ok
        print(json.dumps({"case": page, "ok": ok, "status": result["status"], "chars_in_field": typed,
                          "actions": result.get("actions"), "error": result.get("error")}))
    server.shutdown()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
