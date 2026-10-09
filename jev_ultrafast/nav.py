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
    r"tarjeta|iban|ssn|\bpin\b|user.?name|usuario|login|identifiant|dni|nif",
    re.I,
)


ORDINARY_KEY = re.compile(r"\b(postal|zip|promo|coupon|discount|ape|naf|commune|insee|client|customer|article|"
                          r"product|produit|country|pays)\b", re.I)


def key_words(key):
    """sms_code, otpCode, card-number → 'sms code', 'otp Code', 'card number', so word boundaries apply."""
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", re.sub(r"[_\-.]+", " ", key))


def secret_key(key):
    """A value key that names a secret. A plain "code" qualified as ordinary (postal_code, code_ape) is not one."""
    words = key_words(key)
    if not SECRET.search(words):
        return False
    return not (ORDINARY_KEY.search(words) and not SECRET.search(re.sub(r"\bcode\b", "", words, flags=re.I)))
# Stop before clicks that commit money, delete, reach other people, publish, sign up or grant access. Reversible
# edits (save, update, add, archive, rename) and choices in a list go through: a user can undo them.
IRREVERSIBLE = re.compile(
    r"\b(pay|pay now|payer|payez|payments?|paiement|pagar|pago|buy|acheter|achetez|comprar|purchase|order|commander|"
    r"commandez|passer (?:la )?commande|finalizar compra|check.?out|complete (?:booking|purchase|order)|book|book now|"
    r"reserve now|r[ée]server|r[ée]servez|reservar|delete|supprimer|supprimez|eliminar|borrar|remove|retirer|send|"
    r"envoyer|envoyez|enviar|share|partager|partagez|invite|inviter|invitez|create account|cr[ée]er (?:un|mon) compte|"
    r"register|inscription|"
    r"submit|soumettre|transf[ée]r\w*|virement|publish|publier|post|confirm\w*|valider|accept\w*|aceptar|"
    r"subscribe|s'abonner|suscrib\w*|unsubscribe|d[ée]sinscri\w*|sign.?up|s'inscrire|signer|firmar|r[ée]silier|"
    r"cancel (?:my |the |your )?(?:subscription|order|booking|plan|account|membership)|"
    r"annuler (?:mon |ma |la |le |l')?(?:abonnement|commande|r[ée]servation|compte)|allow|autoriser|permitir|authori[sz]e|i agree|agree|j'accepte|acepto|sell|vendre|vender|trash|"
    r"corbeille|discard|apply now|postuler|d[ée]clarer|declare|se d[ée]connecter|d[ée]connexion|log ?out|sign ?out|"
    r"cerrar sesi[oó]n|abmelden)\b",
    re.I,
)
STATE_DIR = Path.home() / ".cache" / "jevnav"
JOURNAL_DIR = Path.home() / ".claude" / "jev-journal" / "nav"

# Credential test on a live element: type, autocomplete, inputmode and length, not just its label.
# Shared by the field check and the page scan. A secret field (password, one-time code, card, IBAN) is always a
# credential. An identity field (email, username, an unlabeled short numeric box) is one only in a sign-in or
# verification context, so business forms (SIRET, code APE, code commune, a sharing email) are typed normally.
CREDENTIAL_JS = r"""
  // Names are split into words first (otp_code, smsCode, card-number), so word boundaries apply.
  const split = s => (s || '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_\-.]+/g, ' ');
  const words = e => split([e.type, e.name, e.id, e.autocomplete, e.placeholder, e.getAttribute('aria-label'),
    ...(e.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.textContent),
    ...[...(e.labels || [])].map(l => l.textContent)].join(' '));
  const SECRET = /passw|passcode|contraseña|mot de passe|one.?time|\botp\b|\btotp\b|2fa|verification code|code de v[ée]rification|security code|code de s[ée]curit[ée]|\bpin\b|\bcvv\b|\bcvc\b|card number|num[ée]ro de carte|\biban\b/i;
  const ORDINARY = /\b(postal|zip|promo|coupon|descuento|day|month|year|jour|mois|ann[ée]e|d[ií]a|mes|a[ñn]o|quantit\w*|qty|cantidad|amount|montant|siret|siren|ape|naf|commune|insee|tva|vat|search|recherche)\b/i;
  const CODE = /\bcode\b|\bdigits\b|\bchiffres\b|\bc[óo]digo\b/i;
  const IDENTITY = /user.?name|utilisateur|usuario|e-?mail|courriel|identifiant|login|\bdni\b|\bnif\b|customer.?(?:number|id)/i;
  const SIGNIN_URL = /(log.?in|sign.?in|signin|connexion|auth|sso|account|verify|verification|2fa|mfa|identif)/i;
  const SIGNIN_TEXT = /\b(sign.?in|log.?in|se connecter|connectez-vous|identifiez-vous|s'identifier|identification|iniciar sesi[oó]n|anmelden|verify|v[ée]rifi\w*|we sent a code|code (?:sent|envoy[ée])|sms|two.?factor|double authentification|one.?time)\b|(?<!d[ée])connexion/i;
  const shown = e => e.checkVisibility({checkVisibilityCSS: true});
  const context = e => {
    if ([...document.querySelectorAll('input[type=password],input[autocomplete~="one-time-code"]')].some(shown)) return true;
    if (SIGNIN_URL.test(location.hostname + location.pathname + location.hash) || SIGNIN_TEXT.test(document.title)) return true;
    const scope = [e.form, e.closest('dialog,[role=dialog],main')].filter(Boolean);
    const headings = [...document.querySelectorAll('h1,h2,legend,[role=heading]')].filter(shown).map(h => h.innerText).join(' ');
    return SIGNIN_TEXT.test(headings.slice(0, 600)) ||
      scope.some(s => SIGNIN_TEXT.test((s.innerText || '').slice(0, 1500)));
  };
  const isCredential = e => {
    if (!e || e.isContentEditable || e.tagName === 'TEXTAREA' || e.tagName === 'SELECT') return false;
    if (e.type === 'password' || /password|one-time-code|cc-/.test(e.autocomplete || '')) return true;
    const w = words(e);
    if (SECRET.test(w)) return true;
    if (ORDINARY.test(w)) return false;
    // A code field is a one-time code when its label says so (SMS, received, verification, activation) or the
    // page is a sign-in/verification step; "Code client" or "Code article" on a business form is not.
    if (CODE.test(w) && (/sms|re[çc]u|received|sent|envoy|v[ée]rif|s[ée]cur|auth|activation|confirm/i.test(w) || context(e)))
      return true;
    const identity = e.type === 'email' || /username|email/.test(e.autocomplete || '') || IDENTITY.test(w) ||
      (e.maxLength > 0 && e.maxLength <= 8 && /numeric|tel/.test(e.getAttribute('inputmode') || e.type)) ||
      !w.replace(e.type, '').trim();
    return identity && context(e);
  };
"""
FIELD_IS_CREDENTIAL = "(node => {" + CREDENTIAL_JS + " const e = window.__jevFast?.nodes.get(node); return !e || isCredential(e); })"
# A flagged field stays pending while it is shown and empty; once the user or 1Password fills it, the run resumes.
NODE_PENDING = ("(node => { const e = window.__jevFast?.nodes.get(node); "
                "return !!e?.isConnected && e.checkVisibility() && !(e.value ?? e.innerText ?? '').trim(); })")

# Visible credential fields in the viewport, in the first empty one's position (the pause clicks it).
CREDENTIALS = r"""(() => {""" + CREDENTIAL_JS + r"""
  const vis = e => { const r = e.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && e.checkVisibility({checkVisibilityCSS: true})))
      return false;
    // Frameworks such as Ionic draw a styled box over an opacity-0 native input: trust a hit test over opacity.
    const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return e.checkVisibility({checkOpacity: true}) || !!hit && (hit === e || e.contains(hit) || hit.contains(e)); };
  const fields = [...document.querySelectorAll('input')].filter(e => vis(e) &&
    !['hidden', 'submit', 'button', 'checkbox', 'radio', 'search', 'file'].includes(e.type) && isCredential(e));
  const first = fields.find(e => !e.value) || fields[0];
  if (!first) return null;
  const r = first.getBoundingClientRect();
  return {count: fields.length, x: r.x + r.width / 2, y: r.y + r.height / 2, url: location.href};
})()"""

# A busy state next to the control just used means a DONE answer may be premature (Jev reads "Wait for it..."
# as finished). Page-wide text is not enough: result pages keep lines such as "Loading prices." forever.
LOADING = r"""(node => {
  const shown = e => e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
  // Step bars (a progressbar with a value) are not loading states; spinners and busy regions are.
  if ([...document.querySelectorAll('[aria-busy="true"],progress:not([value]),[role="progressbar"]:not([aria-valuenow])')]
      .some(shown)) return true;
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


ALARM = {"acting": False, "expired": False}


def deadline_reached(_signum, _frame):
    # Never cut an action in half (between press and release, or before it is recorded): finish it, then stop.
    if ALARM["acting"]:
        ALARM["expired"] = True
        return
    raise Stop("in_progress", reason="deadline")


def run(args):
    if args.deadline:
        signal.signal(signal.SIGALRM, deadline_reached)
        signal.alarm(int(args.deadline))
    values = json.loads(args.values) if args.values else {}
    refused = [k for k in values if secret_key(k)]
    if refused:
        raise Stop("refused", reason="values look like secrets; 1Password fills those", keys=refused)
    saved = {}
    if args.target:
        path = STATE_DIR / f"{args.target}.json"
        saved = json.loads(path.read_text()) if path.exists() else {}
        if saved.get("goal") != args.goal or saved.get("status") == "done":
            saved = {}
    typed = saved.get("typed", [])
    started = time.perf_counter()
    chooser = value_chooser(values, typed)
    agent = Agent(args.url, args.goal, target=args.target, text_fn=chooser)
    state, browser = agent.state, agent.browser
    raw_act = browser.act

    def guarded_act(*a, **k):  # the deadline alarm may not cut a click or a keystroke in half
        ALARM["acting"] = True
        try:
            return raw_act(*a, **k)
        finally:
            ALARM["acting"] = False

    browser.act = guarded_act
    # Refuse to type when the click left focus on a credential field (e.g. a login modal opened).
    browser.focus_guard = ("(() => {" + CREDENTIAL_JS + " let a = document.activeElement;"
                           " while (a?.shadowRoot?.activeElement) a = a.shadowRoot.activeElement;"
                           " if (a?.tagName === 'IFRAME') return false;"  # an embedded form we cannot inspect, often a login
                           " return !a || a.tagName !== 'INPUT' || !isCredential(a); })()")
    state["history"] = saved.get("history", [])
    status, info, logins, empty_waits, done_waits, last_node = None, {}, 0, 0, 0, None
    cycle, auto_scrolls, stale = [], 0, 0
    confirm = args.confirm
    try:
        while state["status"] not in {"done", "blocked"}:
            if time.perf_counter() - started > args.budget or ALARM["expired"]:
                status = "in_progress"
                break
            try:
                # Single-page apps render after "complete"; an empty page makes Jev answer BLOCKED.
                if not state["page"]["text"].strip() and empty_waits < 20 and \
                        not any(a["kind"] in {"click", "fill", "select"} for a in state["page"]["actions"]):
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
                # Jev tends to answer BLOCKED when the target sits below the visible area. While the page or its
                # panel can still scroll, look further before giving up.
                if decision["choice"] == "BLOCKED" and auto_scrolls < 8 and \
                        any(a["id"] == "scroll_down" for a in state["page"]["actions"]):
                    auto_scrolls += 1
                    decision["choice"] = "scroll_down"
                    decision["probabilities"] = {**decision.get("probabilities", {}), "scroll_down": 0.0}
                if decision["choice"] == "DONE" and done_waits < 2 and browser.evaluate(f"{LOADING}({json.dumps(last_node)})"):
                    # Wait in the page (up to 3 s) for the busy state to clear, then ask once more.
                    done_waits += 1
                    until = time.monotonic() + 3
                    while time.monotonic() < until and browser.evaluate(f"{LOADING}({json.dumps(last_node)})"):
                        time.sleep(0.2)
                    state["decision"], state["status"] = None, "ready"
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
                # Judge the control by its own name, not the row text appended for Jev. A control without an
                # accessible name (only a test-id hint or its role) is unknown, unless it merely opens a menu.
                own = (action or {}).get("base") or label
                generic = own.strip().lower() in {"", "button", "link", "menuitem", "option", "tab"} or \
                    ((action or {}).get("named") is False and not (action or {}).get("menu"))
                if action and action["kind"] in {"click", "select"} and (IRREVERSIBLE.search(own) or generic):
                    if not (confirm and confirm.lower() in label.lower()):
                        raise Stop("confirm", action=label)
                steps = len(state["history"])
                try:
                    agent.command("act", {"fingerprint": state["page"]["fingerprint"]})
                except ValueError as e:
                    if "No single option" in str(e):  # a long list with no option matching the supplied value
                        raise Stop("need_value", field=label, reason=str(e)) from None
                    raise
                finally:
                    # One irreversible click per --confirm, spent as soon as the click is recorded (even if the
                    # page then navigates and the next read goes stale).
                    if len(state["history"]) > steps and action and confirm and confirm.lower() in label.lower() and \
                            (IRREVERSIBLE.search(own) or generic):
                        confirm = None
                if action and action["kind"] == "click":
                    last_node = action["node"]
                stale = 0
                helper = (state["history"][-1].get("text_helper") or "") if len(state["history"]) > steps else ""
                if helper.startswith("values:"):  # count a value only once it was actually typed
                    typed.append(helper[len("values:"):])
                # Jev can cycle between two page states (a menu opening and closing), which the upstream no-change
                # check misses: stop after 8 such actions instead of running to the step cap. Steppers, pagination
                # and date pickers repeat a label too, but each click reaches a new page state, so they pass.
                if action and action["kind"] not in {"scroll", "wait"}:
                    cycle = (cycle + [(label, state["page"]["fingerprint"])])[-8:]
                    if len(cycle) == 8 and len({c[0] for c in cycle}) <= 2 and len({c[1] for c in cycle}) <= 2:
                        raise Stop("blocked", reason="loop", actions=sorted({c[0] for c in cycle}))
            except StalePage:
                stale += 1
                if stale >= 6:  # the chosen target keeps failing its pre-input check (covered, moving, disabled)
                    raise Stop("blocked", reason="unreachable") from None
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
        (STATE_DIR / f"{browser.target}.json").write_text(
            json.dumps({"goal": args.goal, "status": status, "history": history, "typed": typed}))
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
