"""Run one jevnav task in-process and print where the time went: Jev calls, page reads, actions, other CDP calls,
sleeps. Same arguments as jevnav. Diagnostic only."""
import collections, json, sys, time
from jev_ultrafast import agent, browser, model, nav

T = collections.defaultdict(float); N = collections.Counter()


def timed(name, fn):
    def wrap(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            T[name] += time.perf_counter() - t; N[name] += 1
    return wrap


agent.choose = timed("jev", agent.choose)
browser.Browser.read = timed("read", browser.Browser.read)
browser.Browser.act = timed("act", browser.Browser.act)
browser.Browser.evaluate = timed("evaluate", browser.Browser.evaluate)
browser.Browser.__init__ = timed("open", browser.Browser.__init__)
real_sleep = time.sleep
nav.time.sleep = timed("sleep(nav)", real_sleep)
t0 = time.perf_counter()
sys.argv = ["jevnav", *sys.argv[1:]]
try:
    nav.main()
except SystemExit:
    pass
total = time.perf_counter() - t0
print(json.dumps({"total_s": round(total, 2), **{k: [round(v, 2), N[k]] for k, v in sorted(T.items(), key=lambda x: -x[1])}}),
      file=open("/tmp/jevnav-profile.json" if len(sys.argv) < 0 else __import__("os").environ.get("PROF_OUT", "/dev/stderr"), "a"))
