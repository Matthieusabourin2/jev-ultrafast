"""jevnav: one Bash call drives the user's own browser profile and prints a JSON result.

Field values come from the caller (--values), never from a text LLM; Jev picks which value goes where.
Credentials are never typed: a login form pauses the run until 1Password fills it and the user submits.
A click whose label looks irreversible stops with status "confirm" unless the caller passes --confirm.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from .agent import Agent
from .browser import StalePage
from .model import post_json, validate_choice

SECRET = re.compile(
    r"passw|passcode|\bpass\b|pwd|mdp|mot.?de.?passe|contraseña|secret|token|otp|totp|2fa|\bcode\b|cvv|cvc|card|carte|"
    r"tarjeta|iban|ssn|\bpin\b|user.?name|usuario|login|identifiant|e-?mail|dni|nif",
    re.I,
)
IRREVERSIBLE = re.compile(
    r"\b(pay\w*|paiement|pag(?:o|ar)|buy|acheter|compr(?:ar|a)|purchase|order|commander|commande|check.?out|book|booking|book now|"
    r"r[ée]serv\w*|delete|supprimer|eliminar|borrar|remove|retirer|send|envoyer|enviar|submit|soumettre|transfer\w*|"
    r"virement|publish|publier|post|confirm\w*|valider|accept\w*|aceptar|subscribe|s'abonner|suscrib\w*|"
    r"unsubscribe|désinscri\w*|sign.?up|signer|firmar|inscri\w*|registr\w*|cancel\w*|annuler|save|enregistrer|guardar|update|modifier|allow|autoriser|permitir|authori[sz]e|"
    r"i agree|agree|j'accepte|acepto|sell|vendre|vender|archive\w*|trash|corbeille|discard|apply now|postuler)\b",
    re.I,
)
STATE_DIR = Path.home() / ".cache" / "jevnav"
JOURNAL_DIR = Path.home() / ".claude" / "jev-journal" / "nav"

# Credential test on a live element: type, autocomplete, inputmode and length, not just its label.
IS_CREDENTIAL = r"""e => { const w = [e.type, e.name, e.id, e.autocomplete, e.placeholder, e.getAttribute('aria-label'),
    ...(e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.textContent),
    ...[...(e.labels || [])].map(l => l.textContent)].join(' ');
  if (e.type === 'password' || /password|username|one-time-code|cc-/.test(e.autocomplete || '')) return true;
  // Ordinary short fields: postal codes, dates, quantities, promo codes.
  if (/postal|zip|promo|coupon|descuento|day|month|year|jour|mois|année|día|mes|año|quantit|qty|cantidad|amount|montant/i.test(w)) return false;
  return e.type === 'email' || /email/.test(e.autocomplete || '') ||
    (e.maxLength > 0 && e.maxLength <= 8 && /numeric|tel/.test(e.getAttribute('inputmode') || e.type)) ||
    /passw|passcode|contraseña|mot de passe|one-time|otp|\bpin\b|user.?name|utilisateur|usuario|e-?mail|courriel|identifiant|login|\bdni\b|\bnif\b|customer.?(?:number|id)|\bcode\b|código|\bcodice\b|digits|chiffres/i.test(w) ||
    !w.replace(e.type, '').trim(); }"""
FIELD_IS_CREDENTIAL = "(node => { const e = window.__jevFast?.nodes.get(node); return !e || (" + IS_CREDENTIAL + ")(e); })"
# A flagged field stays pending while it is shown and empty; once the user or 1Password fills it, the run resumes.
NODE_PENDING = "(node => { const e = window.__jevFast?.nodes.get(node); return !!e?.isConnected && e.checkVisibility() && !e.value; })"

# Visible credential fields in the viewport. A password or one-time-code field always counts; an email/username
# field counts only inside a sign-in form or page, so newsletter boxes and site headers do not pause the run.
CREDENTIALS = r"""(() => {
  const vis = e => { const r = e.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && e.checkVisibility({checkVisibilityCSS: true})))
      return false;
    // Frameworks such as Ionic draw a styled box over an opacity-0 native input: trust a hit test over opacity.
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return e.checkVisibility({checkOpacity: true}) || !!hit && (hit === e || e.contains(hit) || hit.contains(e)); };
  const words = e => [e.type, e.name, e.id, e.autocomplete, e.placeholder, e.getAttribute('aria-label'),
    ...[...(e.labels || [])].map(l => l.textContent)].join(' ');
  const inputs = [...document.querySelectorAll('input')].filter(e => vis(e) &&
    !['hidden', 'submit', 'button', 'checkbox', 'radio', 'search', 'file'].includes(e.type));
  const secret = inputs.filter(e => e.type === 'password' || /one-time-code|current-password|new-password/.test(e.autocomplete) ||
    /passw|mot de passe|contraseña|one-time|verification code|code de vérification/i.test(words(e)));
  const SIGNIN = /sign.?in|log.?in|connexion|se connecter|identifi|iniciar sesi|acceder|entrar|anmelden/i;
  const scope = e => { let a = e; for (let i = 0; i < 6 && a.parentElement; i++) a = a.parentElement;
    return (e.form || a).innerText || ''; };
  const user = inputs.filter(e => (e.type === 'email' || /username|email/.test(e.autocomplete) ||
    /user.?name|utilisateur|e-?mail|courriel|identifiant|login|usuario|dni|nif|nie|documento|phone|téléphone|teléfono|mobile|móvil/i.test(words(e)) ||
    (e.type === 'tel' || /\btel\b/.test(e.autocomplete))) &&
    (secret.length || SIGNIN.test(document.title + ' ' + location.href) || SIGNIN.test(scope(e).slice(0, 2000))));
  const fields = [...user, ...secret];
  const first = fields.find(e => !e.value) || fields[0];
  if (!first) return null;
  const r = first.getBoundingClientRect();
  return {count: fields.length, x: r.x + r.width / 2, y: r.y + r.height / 2, url: location.href};
})()"""

# A busy state next to the control just used means a DONE answer may be premature (Jev reads "Wait for it..."
# as finished). Page-wide text is not enough: result pages keep lines such as "Loading prices." forever.
LOADING = r"""(node => {
  const shown = e => e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
  if ([...document.querySelectorAll('[aria-busy="true"],progress,[role="progressbar"]')].some(shown)) return true;
  let a = window.__jevFast?.nodes.get(node);
  if (!a?.isConnected) return false;
  for (let i = 0; i < 3 && a.parentElement; i++) a = a.parentElement;
  return /wait for it|loading|please wait|chargement|veuillez patienter|cargando|espere/i.test(a.innerText || '');
})"""

VALUE_RULES = """Choose which caller-supplied value belongs in the selected field, using the field label,
its current value, the page, the goal, and values already typed. Labels can be indirect: a search box opened
to change a prefilled field (e.g. "Where else?" over an origin) takes that field's value. Choose NONE only
when the field clearly asks for information that none of the supplied values describe."""


class Stop(Exception):
    def __init__(self, status, **info):
        super().__init__(status)
        self.status, self.info = status, info


def value_chooser(values, typed):
    """Jev picks a key from the caller's values; a field without a matching value stops the run."""

    def text_fn(context):
        field = context["field"]["label"]
        if not values:
            raise Stop("need_value", field=field)
        criteria = {k: f"{k}: {v}" for k, v in values.items()}
        criteria["NONE"] = "None of the supplied values belongs in this field."
        started = time.perf_counter()
        body = {
            "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
            "state": {**context, "already_typed": typed},
            "questions": {"value": {"type": "choice", "criteria": criteria,
                                    "instructions": {"goal": context["goal"], "rules": VALUE_RULES}}},
        }
        result = post_json("https://api.typesafe.ai/v1/systemone", os.environ["TYPESAFE_API_KEY"], body)
        text_fn.input_tokens += result.get("usage", {}).get("input_tokens", 0)
        key = validate_choice(result["answers"].get("value", {}), criteria)["choice"]
        if key == "NONE":
            raise Stop("need_value", field=field)
        return values[key], {"model": f"values:{key}", "latency_ms": round((time.perf_counter() - started) * 1000),
                             "usage": result.get("usage", {})}

    text_fn.input_tokens = 0
    return text_fn


def node_center(browser, node):
    return browser.evaluate(f"""(node => {{ const r = window.__jevFast.nodes.get(node).getBoundingClientRect();
      return {{count: 1, x: r.x + r.width / 2, y: r.y + r.height / 2}}; }})({node})""")


def login_pause(browser, wait_s, node=None):
    """Bring the tab forward, focus the credential field, and wait for the user and 1Password.

    node: an observed field Jev wanted to type into that the live check flagged as a credential."""
    found = node_center(browser, node) if node is not None else browser.evaluate(CREDENTIALS)
    if not found:
        return False
    try:
        return wait_for_login(browser, wait_s, node, found)
    finally:
        browser.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)


def wait_for_login(browser, wait_s, node, found):
    browser.call("Emulation.clearDeviceMetricsOverride")
    from browser_harness.helpers import cdp

    cdp("Target.activateTarget", targetId=browser.target)
    app = os.environ.get("JEVNAV_APP", "Comet")  # the macOS app that owns the CDP profile
    subprocess.run(["osascript", "-e", f'tell application "{app}" to activate'], check=False)
    # Clearing the viewport override re-lays out the page: click only once the field has stopped moving.
    last = None
    for _ in range(15):
        time.sleep(0.2)
        found = (node_center(browser, node) if node is not None else browser.evaluate(CREDENTIALS)) or found
        if last and (round(found["x"]), round(found["y"])) == last:
            break
        last = (round(found["x"]), round(found["y"]))
    # A real click (not JS focus) is what makes the 1Password extension offer its inline menu.
    for event in ("mousePressed", "mouseReleased"):
        browser.call("Input.dispatchMouseEvent", type=event, x=found["x"], y=found["y"], button="left", clickCount=1)
    subprocess.run(["osascript", "-e", 'display notification "Remplis avec 1Password, puis clique le bouton de connexion (Access, Se connecter…)" with title "jevnav : connexion"'],
                   check=False)
    deadline, clear_since = time.monotonic() + wait_s, None
    while time.monotonic() < deadline:
        time.sleep(0.5)
        try:
            still = browser.evaluate(CREDENTIALS) or (node is not None and browser.evaluate(f"{NODE_PENDING}({node})"))
        except StalePage:
            still = True  # navigating
        if still:
            clear_since = None
        elif clear_since is None:
            clear_since = time.monotonic()
        elif time.monotonic() - clear_since >= 1.5:
            return True
    raise Stop("login_timeout", field_count=found["count"])


def deadline_reached(_signum, _frame):
    raise Stop("in_progress", reason="deadline")


def run(args):
    if args.deadline:
        signal.signal(signal.SIGALRM, deadline_reached)
        signal.alarm(int(args.deadline))
    values = json.loads(args.values) if args.values else {}
    refused = [k for k in values if SECRET.search(k)]
    if refused:
        raise Stop("refused", reason="values look like secrets; 1Password fills those", keys=refused)
    saved = {}
    if args.target:
        path = STATE_DIR / f"{args.target}.json"
        saved = json.loads(path.read_text()) if path.exists() else {}
        if saved.get("goal") != args.goal:
            saved = {}
    typed = saved.get("typed", [])
    started = time.perf_counter()
    chooser = value_chooser(values, typed)
    agent = Agent(args.url, args.goal, target=args.target, text_fn=chooser)
    state, browser = agent.state, agent.browser
    # Refuse to type when the click left focus on a credential field (e.g. a login modal opened).
    browser.focus_guard = ("(() => { let a = document.activeElement; while (a?.shadowRoot?.activeElement) a = a.shadowRoot.activeElement;"
                           " if (a?.tagName === 'IFRAME') return false;"  # an embedded form we cannot inspect, often a login
                           " return !a || a.tagName !== 'INPUT' || !(" + IS_CREDENTIAL + ")(a); })()")
    state["history"] = saved.get("history", [])
    status, info, logins, empty_waits, done_waits, last_node = None, {}, 0, 0, 0, None
    confirm = args.confirm
    try:
        while state["status"] not in {"done", "blocked"}:
            if time.perf_counter() - started > args.budget:
                status = "in_progress"
                break
            try:
                # Single-page apps render after "complete"; an empty page makes Jev answer BLOCKED.
                if not state["page"]["text"].strip() and empty_waits < 20:
                    empty_waits += 1
                    time.sleep(0.5)
                    state["page"] = browser.observe(screenshot=False)
                    continue
                if login_pause(browser, args.login_wait):
                    logins += 1
                    state["page"] = browser.observe(screenshot=False)
                    continue
                agent.command("predict")
                decision = state["decision"]
                if decision["choice"] == "DONE" and done_waits < 20 and browser.evaluate(f"{LOADING}({json.dumps(last_node)})"):
                    done_waits += 1
                    state["decision"], state["status"] = None, "ready"
                    time.sleep(0.3)
                    state["page"] = browser.observe(screenshot=False)
                    continue
                action = next((a for a in state["page"]["actions"] if a["id"] == decision["choice"]), None)
                if action and action["kind"] == "fill" and browser.evaluate(f"{FIELD_IS_CREDENTIAL}({action['node']})"):
                    state["decision"] = None
                    if not login_pause(browser, args.login_wait, node=action["node"]):
                        raise StalePage("Credential field vanished")
                    logins += 1
                    state["page"] = browser.observe(screenshot=False)
                    continue
                label = (action or {}).get("label", "")
                generic = label.strip().lower() in {"", "button", "link", "menuitem", "option", "tab"}
                if action and action["kind"] in {"click", "select"} and (IRREVERSIBLE.search(label) or generic):
                    if not (confirm and confirm.lower() in label.lower()):
                        raise Stop("confirm", action=label)
                    confirm = None  # one irreversible click per --confirm
                steps = len(state["history"])
                agent.command("act", {"fingerprint": state["page"]["fingerprint"]})
                if action and action["kind"] == "click":
                    last_node = action["node"]
                helper = (state["history"][-1].get("text_helper") or "") if len(state["history"]) > steps else ""
                if helper.startswith("values:"):  # count a value only once it was actually typed
                    typed.append(helper[len("values:"):])
            except StalePage:
                state["decision"], state["status"] = None, "ready"
                time.sleep(0.2)
                try:
                    state["page"] = browser.observe(screenshot=False)
                except StalePage:
                    pass
    except Stop as stop:
        status, info = stop.status, stop.info
    except Exception as e:  # noqa: BLE001 - keep the target and state so the caller can resume
        status, info = "error", {"error": f"{type(e).__name__}: {e}"}
    signal.alarm(0)  # never interrupt the result and state writes
    status = status or state["status"]
    page = state["page"]
    history = [{k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in state["history"]]
    result = {
        "status": status,
        **info,
        "elapsed_s": round(time.perf_counter() - started, 2),
        "nav_s": round(state["elapsed_ms"] / 1000, 2),  # after the first page load, as in the upstream benchmarks
        "logins": logins,
        "actions": [h["action"] + (f" ← {h['text']!r}" if h.get("text") else "") for h in history],
        "url": page["url"],
        "title": page["title"],
        "text": page["text"][: args.text_chars],
        "target": browser.target,
        "steps": len(state["history"]) - len(saved.get("history", [])),
        "jev_input_tokens": chooser.input_tokens + sum(d.get("usage", {}).get("input_tokens", 0) for d in state["decisions"]),
    }
    if status in {"done", "blocked"} and args.close:
        agent.close()
        result["target"] = None
    else:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / f"{browser.target}.json").write_text(json.dumps({"goal": args.goal, "history": history, "typed": typed}))
    return result


def log(args, result):
    """One line per run for the weekly review: domain, status, counts and timings only, never values or page text."""
    url = args.url or result.get("url") or ""
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": os.environ.get("JEVNAV_SOURCE", "use"),
             "domain": urlsplit(url).hostname or "", "resumed": bool(args.target),
             "status": result["status"]}
    entry |= {k: result[k] for k in ("steps", "logins", "elapsed_s", "nav_s", "jev_input_tokens") if k in result}
    try:
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL_DIR / f"{time.strftime('%Y-%m-%d')}.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # the journal must never break a run


def main():
    p = argparse.ArgumentParser(prog="jevnav", description=__doc__)
    p.add_argument("--goal", required=True)
    p.add_argument("--url", help="start URL; omit with --target to continue where the tab is")
    p.add_argument("--values", help='JSON object of non-secret field values, e.g. {"from":"Zurich"}')
    p.add_argument("--target", help="resume this tab (target id from a previous result)")
    p.add_argument("--confirm", help="allow one irreversible click whose label contains this text")
    p.add_argument("--close", action="store_true", help="close the tab when done or blocked")
    p.add_argument("--budget", type=float, default=90, help="seconds of navigation before returning in_progress")
    p.add_argument("--login-wait", type=float, default=120)
    p.add_argument("--deadline", type=float, help="hard wall-clock limit in seconds; returns in_progress with the target")
    p.add_argument("--text-chars", type=int, default=3000)
    args = p.parse_args()
    if not args.url and not args.target:
        p.error("--url or --target is required")
    try:
        result = run(args)
    except Stop as stop:
        result = {"status": stop.status, **stop.info}
    except Exception as e:  # noqa: BLE001 - the caller needs a JSON status, not a traceback
        result = {"status": "error", "error": f"{type(e).__name__}: {e}"}
    log(args, result)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["status"] in {"done", "confirm", "need_value", "in_progress"} else 1)


if __name__ == "__main__":
    main()
