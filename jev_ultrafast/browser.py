"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import sys
import time
from pathlib import Path

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

# Atomically read visible content and controls, preserving actual DOM node identity.
READ_STATE = Path(__file__).with_name("snapshot.js").read_text()
MARKER = f"(() => {{ const state={READ_STATE}; return state?.marker ?? null; }})()"

# Resolve once no structure, text or state attribute has changed for QUIET ms, or after CAP ms.
SETTLE = """new Promise(resolve => {
  const QUIET=75, CAP=400; let timer;
  const finish=()=>{observer.disconnect(); clearTimeout(cap); resolve(true)};
  const observer=new MutationObserver(()=>{clearTimeout(timer); timer=setTimeout(finish,QUIET)});
  observer.observe(document,{subtree:true,childList:true,characterData:true,attributes:true,
    attributeFilter:['aria-expanded','aria-selected','aria-checked','aria-hidden','aria-disabled','disabled','hidden','value']});
  timer=setTimeout(finish,QUIET);
  const cap=setTimeout(()=>{observer.disconnect(); clearTimeout(timer); resolve(false)},CAP);
})"""


class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class Browser:
    def __init__(self, url, target=None):
        ensure_daemon()
        # An existing target lets a caller resume the same tab across runs.
        self.target = target or cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        # Keep rAF/menus rendering in an owned background tab, without activating the user's Chrome tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        if url:
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
        # Pages keep rendering after load or input (hydration, suggestion lists). A decision made on an unsettled
        # read fails the freshness check and costs a second model call, so wait in the page until the DOM has been
        # quiet for a short window (one round trip, capped).
        try:
            self.call("Runtime.evaluate", expression=SETTLE, awaitPromise=True, returnByValue=True)
        except Exception:  # noqa: BLE001 - a frozen tab or a navigation: read the page as it is
            pass
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
        if action is not None and action["kind"] in {"click", "select"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"
            )
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.evaluate(MARKER) == page["marker"]

    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(0.1)
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text,
                                    "focus_guard": getattr(self, "focus_guard", None)})
        self.after_input = action if action["kind"] != "wait" else None
        return result

    def close(self):
        if self.target:
            cdp("Target.closeTarget", targetId=self.target)
            self.target = None


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
            # Hover the element first: rows reveal (and enable) their controls on hover, as for a hand.
            spot = kind in {"click", "fill"} and evaluate("""(node => { const e=window.__jevFast?.nodes.get(node); if (!e?.isConnected) return null;
              e.scrollIntoView({block:'nearest',inline:'nearest'}); const r=e.getBoundingClientRect();
              return {x:r.x+r.width/2, y:r.y+r.height/2}; })(""" + json.dumps(action["node"]) + ")")
            if spot:
                call("Input.dispatchMouseEvent", type="mouseMoved", x=spot["x"], y=spot["y"])
                time.sleep(0.05)  # let :hover styles apply before the hit test
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors.
            target = evaluate("""(action => {
              const e=window.__jevFast?.nodes.get(action.node);
              if (e?.isConnected) e.scrollIntoView({block:'nearest',inline:'nearest'});
              if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
                  !e.checkVisibility({checkVisibilityCSS:true})) return null;
              if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
              const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
              if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
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
            })(""" + json.dumps({**action, "text": request.get("text")}) + ")")
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
