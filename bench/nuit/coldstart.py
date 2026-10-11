"""First Jev call of a fresh process, cold or after a connection warm-up done while the page loads. Usage: coldstart.py MODE"""
import json, os, sys, time
from pathlib import Path
from jev_ultrafast.model import CLIENT, post_json

URL = "https://api.typesafe.ai/v1/systemone"
body = json.loads(open(Path(__file__).with_name("requests") / "flights.jsonl").readline())["request"]
if sys.argv[1] == "warm":
    try:
        CLIENT.get("https://api.typesafe.ai/", timeout=3)
    except Exception:  # noqa: BLE001 - only the TLS connection matters
        pass
    time.sleep(0.3)  # the page would still be loading
t = time.perf_counter()
post_json(URL, os.environ["TYPESAFE_API_KEY"], body)
print(round((time.perf_counter() - t) * 1000))
