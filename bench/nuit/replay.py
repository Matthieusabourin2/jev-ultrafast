"""Replay recorded Jev requests offline, as recorded and in variants, alternating; report latency and whether the
answer (operation + target label) stays the same. Usage: replay.py VARIANT [rounds]"""
import copy, gzip, json, os, statistics, sys, time
from pathlib import Path
from jev_ultrafast.model import CLIENT, post_json

URL = "https://api.typesafe.ai/v1/systemone"


def answer(body, result):
    op = result["answers"]["operation"]["choice"]
    tq = result["answers"].get(op.lower() + "_target")
    label = None
    if tq:
        crit = body["questions"][op.lower() + "_target"]["criteria"].get(tq["choice"], {})
        label = crit.get("element", "").split("] ", 1)[-1]
    return op, label


def variant(name, body):
    b = copy.deepcopy(body)
    st = b["state"]
    if name == "same":
        pass
    elif name.startswith("model:"):
        b["model"] = name[6:]
    elif name.startswith("text"):  # text3000: page text capped
        st["page"]["text"] = st["page"]["text"][: int(name[4:])]
    elif name == "notext":
        st["page"]["text"] = ""
    elif name.startswith("label"):  # label60: element labels capped
        n = int(name[5:])
        for e in st["elements"]:
            e["label"] = e["label"][:n]
        for q in b["questions"].values():
            for c in q["criteria"].values():
                if isinstance(c, dict) and "element" in c:
                    c["element"] = c["element"][: n + 6]
    elif name == "noelements":  # elements only in the target questions, not repeated in the state
        st["elements"] = [{"index": e["index"], "operations": e["operations"]} for e in st["elements"]]
    elif name.startswith("hist"):
        st["recent_actions"] = st["recent_actions"][-int(name[4:]):]
    elif name.startswith("cap"):  # cap40: only the first N elements offered (state and target questions)
        n = int(name[3:])
        keep = {e["index"] for e in st["elements"][:n]}
        st["elements"] = st["elements"][:n]
        for q in b["questions"].values():
            if "criteria" in q and q.get("type") != "choice" and all(k.isdigit() for k in q["criteria"]):
                q["criteria"] = {k: v for k, v in q["criteria"].items() if k in keep}
    elif name == "noinstr":  # the questions' instructions left out
        for q in b["questions"].values():
            q.pop("instructions", None)
    elif name == "notyping":  # the typing question dropped when the page has no field to type in
        if not any("TYPE_TEXT" in e.get("operations", []) or "TYPE" in " ".join(e.get("operations", [])) for e in st["elements"]):
            b["questions"].pop("type_text_target", None)
    elif name == "noempty":  # empty values and "expanded: false" dropped from elements and criteria
        for e in st["elements"]:
            for k in [k for k, v in e.items() if v in ("", "false") and k in ("value", "expanded")]:
                del e[k]
        for q in b["questions"].values():
            for c in q["criteria"].values():
                if isinstance(c, dict):
                    for k in [k for k, v in c.items() if v in ("", "false") and k in ("current_value", "expanded")]:
                        del c[k]
    elif name == "slimcriteria":  # target criteria keep only the element line (role and value already in the state)
        for q in b["questions"].values():
            for i, c in list(q["criteria"].items()):
                if isinstance(c, dict) and "element" in c:
                    q["criteria"][i] = {"element": c["element"]}
    return b


def send(name, key, body):
    if name == "compact":  # no spaces in the JSON sent
        r = CLIENT.post(URL, content=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode(),
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        r.raise_for_status()
        return r.json()
    if name == "gzip":
        r = CLIENT.post(URL, content=gzip.compress(json.dumps(body).encode()),
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                 "Content-Encoding": "gzip"})
        r.raise_for_status()
        return r.json()
    return post_json(URL, key, body)


def main():
    name, rounds = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1
    key = os.environ["TYPESAFE_API_KEY"]
    rows = [json.loads(l) for f in sorted(Path(__file__).with_name("requests").glob("*.jsonl")) for l in open(f)]
    lat = {"same": [], name: []}; agree = 0; n = 0; size = {"same": [], name: []}
    for r in range(rounds):
        for row in rows:
            order = ["same", name] if (r + n) % 2 == 0 else [name, "same"]
            got = {}
            for v in order:
                body = variant(v, row["request"])
                size[v].append(len(json.dumps(body)))
                t = time.perf_counter(); res = send(v, key, body); lat[v].append(time.perf_counter() - t)
                got[v] = answer(body, res)
            agree += got["same"] == got[name]; n += 1
    print(json.dumps({"variant": name, "n": n, "agree": f"{agree}/{n}",
                      "median_ms": {k: round(statistics.median(v) * 1000) for k, v in lat.items()},
                      "mean_ms": {k: round(statistics.mean(v) * 1000) for k, v in lat.items()},
                      "bytes": {k: round(statistics.mean(v)) for k, v in size.items()}}, ensure_ascii=False))


main()
