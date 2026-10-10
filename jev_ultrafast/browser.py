"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

# Atomically read visible content and controls, preserving actual DOM node identity.
READ_STATE = Path(__file__).with_name("snapshot.js").read_text()
MARKER = f"(() => {{ const state={READ_STATE}; return state?.marker ?? null; }})()"
# When Jev chooses to wait, wait in the page for the update to finish: until the DOM has been quiet for 150 ms after
# changing, or 0.3 s without any change, at most 1 s. One wait then covers a result list loading, instead of a
# model call per 0.1 s pause.
WAIT = """new Promise(resolve => {
  let quiet; const done=()=>{observer.disconnect(); clearTimeout(cap); resolve(true)};
  const observer=new MutationObserver(()=>{clearTimeout(quiet); quiet=setTimeout(done,150)});
  observer.observe(document,{subtree:true,childList:true,characterData:true});
  quiet=setTimeout(done,300); const cap=setTimeout(done,1000);
})"""



class AllowNeeded(RuntimeError):
    """The browser is not running, or it waits for the user to allow remote debugging."""


class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class Browser:
    def __init__(self, url, target=None):
        # Without a bound, a pending "Allow remote debugging?" sheet makes the daemon wait forever, silently.
        try:
            ensure_daemon(wait=float(os.environ.get("JEVNAV_ALLOW_WAIT", 45)))
        except Exception as e:  # noqa: BLE001 - say what the user has to do
            raise AllowNeeded("The browser is closed or waits for its 'Allow' click (remote debugging).") from e
        # An existing target lets a caller resume the same tab across runs.
        self.target = target or cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        # Keep rAF/menus rendering in an owned background tab, without activating the user's Chrome tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        if url:
            try:
                self.call("Page.navigate", url=url)
            except Exception as e:  # noqa: BLE001 - a busy daemon times out once in a while: one more try,
                # unless the first request already left (a one-shot link must not be loaded twice)
                if "timed out" not in str(e) or self.evaluate("location.href") != "about:blank":
                    raise
                self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.02)

    def call(self, method, **params):
        return cdp(method, session_id=self.session, **params)

    def evaluate(self, expression):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def observe(self, screenshot=True):
        if getattr(self, "after_input", None):
            action, self.after_input = self.after_input, None
            # This is read-only and happens after execution was logged, even if navigation interrupts it.
            try:
                self.call(
                    "Runtime.evaluate",
                    expression="""(action => new Promise(resolve => {
                      const field=window.__jevFast?.nodes.get(action.node);
                      const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
                      let frames=0, stopped=false;
                      const finish=()=>{stopped=true;resolve()};
                      setTimeout(finish,autocomplete ? 200 : 50);
                      const ready=()=>{
                        if (stopped) return;
                        const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
                          .split(/\\s+/).filter(Boolean);
                        const roots=ids.length ? ids.map(id=>document.getElementById(id)).filter(Boolean) : [document];
                        const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
                        if (++frames>=2 && (!autocomplete || options.some(e=>{
                          const r=e.getBoundingClientRect();
                          return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
                            e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
                        }))) finish();
                        else requestAnimationFrame(ready);
                      };
                      requestAnimationFrame(ready);
                    }))(""" + json.dumps(action) + ")",
                    awaitPromise=True,
                    returnByValue=True,
                )
            except RuntimeError:
                pass
        # No settle wait here: measured on Flights, waiting for a quiet DOM cost more (2.2 s a run) than the stale
        # decisions it saved. A stale decision fails the freshness check and is simply made again.
        page = self.read(screenshot)
        return page

    def read(self, screenshot):
        for attempt in range(10):
            try:
                return browser_operation(
                    {"operation": "observe", "session": self.session, "screenshot": screenshot}
                )
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        if action is not None and action["kind"] == "wait":  # waiting is right whatever changed meanwhile
            return True
        if action is not None and getattr(self, "strict", False) and type(action.get("node")) is int:
            # A committing click: same full URL and title, the control exactly as seen (row text, digits included),
            # and its dialog's text unchanged. The rest of the page may live (a checkout countdown).
            node = action["node"]
            current = self.evaluate(
                "(() => { const c=window.__jevFast, e=c?.nodes.get(%d); return c ? [location.href, document.title, "
                "c.guard(e), c.dialogText(e?.closest('dialog,[role=\"dialog\"],[role=\"alertdialog\"]'))] : null; })()"
                % node)
            return current == [page["url"], page["title"], page["guards"].get(str(node)),
                               page.get("dialogs", {}).get(str(node), "")]
        if action is not None and action["kind"] in {"click", "select", "fill"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"
            )
            then = page["guards"].get(str(node))
            if not (current and current[0] == page["page_key"] and same_target(current[1], then)):
                return False
            # A name that grew into a committing one ("… sans accepter" + "· 2,99 €") was never judged as such.
            commits = getattr(self, "commits", None)
            return not (commits and then and current[1] and commits(current[1][2] or "") and
                        not commits(then[2] or ""))
        return same_page(self.evaluate(MARKER), page["marker"])

    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            try:
                self.call("Runtime.evaluate", expression=WAIT, awaitPromise=True, returnByValue=True)
            except Exception:  # noqa: BLE001 - a navigation ended the wait: the next read sees the new page
                pass
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text,
                                    "focus_guard": getattr(self, "focus_guard", None)})
        self.after_input = action if action["kind"] != "wait" else None
        return result

    def close(self):
        if self.target:
            cdp("Target.closeTarget", targetId=self.target)
            self.target = None


# What may change in a control while Jev decides: a price or a loading placeholder, nothing else.
PRICE = re.compile(r"[€$£¥][ \u00a0]?\d[\d.,]*|\d[\d.,]*[ \u00a0]?(?:€|euros?|eur|usd|chf|gbp|\$|£)(?!\w)|\?{2,}|"
                   r"[\ue000-\uf8ff]", re.I)
TAIL = re.compile(r"[\s,·(\-–]+(?:" + PRICE.pattern + r"|[\s,.·()\-–])+", re.I)


def same_target(now, then):
    """The control still means what it meant when Jev chose it.

    Content loading while Jev decides (a calendar filling in its prices) may append a price to the name, after a
    separator and in place of a loading placeholder, and change prices in its row. Everything else must be equal:
    role, states, value, link, the name otherwise ("Continue" never becomes "Continue and pay", "2" never "23"),
    and the row's text with its times and dates (a re-sorted list of trains fails)."""
    if now == then:  # unchanged, including a control the guard cannot see
        return True
    if not now or not then or len(now) != len(then):
        return False
    head = lambda name: re.sub(r"[\s?,.·\ue000-\uf8ff-]+$", "", name or "")
    a, b = now[2] or "", head(then[2])
    grew = a == (then[2] or "") or (b and a.startswith(b) and TAIL.fullmatch(a[len(b):]) is not None)
    rows = lambda text: re.sub(r"\s+", " ", PRICE.sub("", text or "")).strip()
    return bool(grew) and now[:2] == then[:2] and now[3:13] == then[3:13] and rows(now[13]) == rows(then[13])


def same_page(now, then):
    """The page Jev judged (DONE, BLOCKED) is still there: only digits of its text may have moved (a clock, a
    countdown, a price); an error message appearing changes words and fails."""
    if not now or not then or len(now) != len(then):
        return now == then
    digitless = lambda m: [*m[:7], re.sub(r"\d", "", m[7] or ""), *m[8:]]
    return digitless(now) == digitless(then)


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def browser_operation(request):
    operation = request["operation"]
    session = request["session"]

    def call(method, **params):
        return cdp(method, session_id=session, **params)

    def evaluate(expression):
        result = call("Runtime.evaluate", expression=expression, returnByValue=True)
        if result.get("exceptionDetails"):
            if operation == "act" and request["action"]["kind"] == "select":
                raise RuntimeError("Dropdown execution was interrupted; inspect before retrying.")
            raise StalePage("Document changed during evaluation")
        return result.get("result", {}).get("value")

    if operation == "act":
        action = request["action"]
        kind = action["kind"]
        if kind == "scroll":
            call("Input.dispatchMouseEvent", type="mouseWheel", x=action.get("x", 550), y=action.get("y", 650),
                 deltaX=0, deltaY=action["delta"])
        elif kind != "wait":
            if type(action["node"]) is not int:
                raise ValueError("Invalid observed node")
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors.
            target_js = """(action => {
              const e=window.__jevFast?.nodes.get(action.node);
              if (e?.isConnected) e.scrollIntoView({block:'nearest',inline:'nearest'});
              if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
                  !e.checkVisibility({checkVisibilityCSS:true})) return null;
              if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
              const r=e.getBoundingClientRect(), {x,y}=window.__jevFast.point(e);
              if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
              if (action.kind==='fill' && e.type==='range') {
                // A counter (travellers, rooms) is set by value, through the native setter so frameworks see it.
                // The pointer lands on the counter's own drawing, never on another layer covering it.
                const hit=document.elementFromPoint(x,y);
                if (!hit || !e.parentElement?.parentElement?.contains(hit)) return null;
                const v=Number(String(action.text||'').trim());
                if (!Number.isFinite(v) || v<Number(e.min||0) || v>Number(e.max||100)) return {nonumber:true};
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,String(v));
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
                return {x,y,chosen:e.value};
              }
              if (!e.contains(document.elementFromPoint(x,y))) return null;
              if (action.kind==='fill' && e.tagName==='SELECT') {
                // Long native lists are filled like text: pick the one option whose label matches the value.
                const norm=s=>s.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
                const want=norm(action.text||''), live=[...e.options].filter(o=>!o.disabled && !o.closest('optgroup[disabled]'));
                const pick=[o=>norm(o.label)===want, o=>norm(o.label).startsWith(want), o=>norm(o.label).includes(want)]
                  .map(test=>live.filter(test)).find(found=>found.length);
                if (!want || !pick || pick.length!==1) return {nomatch:true};
                e.value=pick[0].value;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
                return {x,y,chosen:pick[0].label};
              }
              if (action.kind==='select') {
                if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
                    !o.disabled && !o.closest('optgroup[disabled]'))) return null;
                e.value=action.value;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
              }
              return {x,y};
            })(""" + json.dumps({**action, "text": request.get("text")}) + ")"
            target = evaluate(target_js)
            if target is None and kind in {"click", "fill"}:
                # Rows reveal (and enable) their controls only while hovered, as for a hand: hover, then test again.
                spot = evaluate("""(node => { const e=window.__jevFast?.nodes.get(node); if (!e?.isConnected) return null;
                  e.scrollIntoView({block:'nearest',inline:'nearest'}); return window.__jevFast.point(e); })(""" +
                                json.dumps(action["node"]) + ")")
                if spot:
                    call("Input.dispatchMouseEvent", type="mouseMoved", x=spot["x"], y=spot["y"])
                    time.sleep(0.03)  # let :hover styles apply before the second hit test
                    target = evaluate(target_js)
            if target and target.get("nonumber"):
                raise ValueError(f"{request.get('text')!r} is not a number within the range of {action['label']!r}.")
            if target and target.get("nomatch"):
                raise ValueError(f"No single option of {action['label']!r} matches {request.get('text')!r}.")
            if target and target.get("chosen"):
                return {"executed": action["id"]}
            if target is None:
                if kind == "select":
                    raise RuntimeError("Dropdown execution was not confirmed; inspect before retrying.")
                raise StalePage("Target changed or is covered. Observe again.")
            if kind != "select":
                x, y = target["x"], target["y"]
                for event in ("mousePressed", "mouseReleased"):
                    call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
                if kind == "fill":
                    # A click can move focus (combobox popups do, so can login modals); callers may veto the target.
                    if request.get("focus_guard") and not evaluate(request["focus_guard"]):
                        raise StalePage("Focus moved to a field the caller refuses. Observe again.")
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyDown",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                        commands=["selectAll"],
                    )
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyUp",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                    )
                    call("Input.insertText", text=request["text"])
        return {"executed": action["id"]}

    info = evaluate(READ_STATE)
    if info is None:
        raise StalePage("Document is navigating")
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
    return info
