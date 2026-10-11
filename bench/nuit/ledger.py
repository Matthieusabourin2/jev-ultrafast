"""Append one experiment verdict to bench/nuit/ledger.jsonl (the night's record: it survives context compaction).

usage: ledger.py ID KEPT|DROPPED "title" "hypothesis" "measure" [commit]
"""
import json, sys, time
from pathlib import Path

eid, verdict, title, hypothesis, measure, *rest = sys.argv[1:]
row = {"id": eid, "verdict": verdict, "title": title, "hypothesis": hypothesis, "measure": measure,
       "commit": rest[0] if rest else None, "at": time.strftime("%H:%M")}
with open(Path(__file__).with_name("ledger.jsonl"), "a") as f:
    f.write(json.dumps(row, ensure_ascii=False) + "\n")
print(json.dumps(row, ensure_ascii=False))
