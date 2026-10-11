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
import unicodedata
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from .agent import Agent
from .browser import AllowNeeded, StalePage
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
    r"cerrar sesi[oó]n|abmelden|signaler|report|block|bloquer|akzeptieren|zustimmen|zulassen|einverstanden|accetta|accetto|effacer|quitter|leave|löschen|blockieren|melden|senden|entfernen|bloquear|denunciar)\b",
    re.I,
)
# Two harmless names that contain a committing word: running a search ("Soumettre la recherche") and refusing
# cookies ("Continuer sans accepter"). A refusal tied to a paid subscription (pay-or-ok walls) still stops.
SEARCH_SUBMIT = re.compile(r"(submit|soumettre|valider|lancer|launch)\s+(the |la |ma |une |your )?(search|recherche)\s*",
                           re.I)
DECLINE = re.compile(r"(tout )?refuser( tout| les cookies| et fermer)?|continuer sans accepter|je refuse|non,? merci|"
                     r"bloquer les cookies|block all cookies|"
                     r"reject( all)?( cookies)?|decline( all)?|deny( all)?|(use )?(only )?(necessary|essential)"
                     r"( cookies)?( only)?|(cookies )?n[ée]cessaires? uniquement|uniquement (les cookies )?n[ée]cessaires|"
                     r"rechazar( todo| todas)?|(alle )?ablehnen", re.I)
# A short refusal worded as a sentence: "Non, je préfère refuser", "Je n'accepte rien", "Ne pas accepter".
DECLINE_WORDS = re.compile(r"\brefus\w*|\breject\w*|\bdecline\b|\bdeny\b|\bn['’]accepte (rien|pas)\b|\bsans accepter\b|"
                           r"\bne pas accepter\b|\brejeter\b|\bablehnen\b|\brechazar\b|\bdon['’]?t accept\b", re.I)
PAYWALL = re.compile(r"abonn|subscri|\bpa(y|ie|yer)|€|\$", re.I)
# What may surround the refusal words in a refusal: "Non, je préfère refuser", "Refuser les cookies facultatifs".
# Anything else names a thing being refused ("Refuser la commande", "Reject and block"): not a cookie refusal.
DECLINE_FILLER = {"tout", "toutes", "tous", "les", "des", "cookies", "cookie", "traceurs", "merci", "non", "je",
                  "préfère", "prefere", "sans", "accepter", "continuer", "fermer", "et", "all", "optional", "non",
                  "essentiels", "essentials", "essential", "facultatifs", "optionnels", "rien", "pas", "ne", "i", "no",
                  "thanks", "thank", "you", "rather", "not", "and", "close", "continue", "without", "accepting",
                  "alle", "todas", "todos", "las", "los", "nécessaires", "necessaires", "necessary", "unnecessary"}
# A box that speaks of cookies, strictly: "consent" or "GDPR" alone appear in invitations and trainings too.
COOKIE_STRICT = re.compile(r"cookie|traceur", re.I)


def declines(name):
    """Whether a control's own name refuses (cookies, an offer) without paying: full refusal names, or a short
    sentence holding a refusal word and no accept-all."""
    head = name.split(":")[0].strip().rstrip(".!")
    if PAYWALL.search(name):
        return False
    # Only filler words may remain once the refusal words are taken out ("Refuser et supprimer", "Refuser la
    # commande" still stop).
    rest = re.findall(r"[^\W\d_]+", DECLINE_WORDS.sub(" ", head).lower())
    return bool(DECLINE.fullmatch(head) or (len(head) <= 40 and DECLINE_WORDS.search(head) and
                                            all(w in DECLINE_FILLER for w in rest)))
# A consent banner's accept button, and the words that mark the banner holding it.
CONSENT_ACCEPT = re.compile(r"\b(accept\w*|accepter|j'accepte|tout accepter|agree|allow all|autoriser|aceptar|"
                            r"akzeptieren)\b", re.I)
# A consent banner's way to its second layer, where the refusal often hides (OneTrust, Didomi, Sourcepoint).
CONSENT_SETTINGS = re.compile(r"(param[eéè]tr\w*|personnali[sz]\w*|customi[sz]e|g[ée]rer (mes |les |vos )?(choix|pr[ée]f[ée]rences|cookies|options)|"
                              r"afficher (toutes )?les finalit[ée]s|(manage|customi[sz]e|cookie) (settings|preferences|options|choices)|"
                              r"(more )?options|pr[ée]f[ée]rences|settings|en savoir plus et (personnaliser|param[ée]trer))", re.I)
CONSENT_CONTEXT = re.compile(r"cookie|consent|traceurs|vos donn[ée]es|nos partenaires|privacy|confidentialit", re.I)
# The text of the smallest element holding both controls, if it is banner-sized: the refusal must sit on the same
# banner as the accept button, never elsewhere on the page (an invitation's "Decline" is not a cookie refusal).
SHARED_BOX = """((a, b) => {
  const x=window.__jevFast?.nodes.get(a), y=window.__jevFast?.nodes.get(b); if (!x || !y) return null;
  let box=x.parentElement; while (box && !box.contains(y)) box=box.parentElement;
  while (box && (box.innerText||'').length<150) box=box.parentElement;  // a bare button row: read its banner
  const text=box?.innerText||''; return box && text.length<4000 ? text : null;
})"""


# Refusing what someone sent (an invitation, a quote, a request) reaches that person: it needs approval too.
REFUSES_SOMEONE = re.compile(r"\b(refus\w*|decline\w*|reject\w*|rejeter|deny|ignorer|ignore)\b.{0,25}\b(invitation|invite|"
                             r"devis|quote|demande|request|offre|offer|candidature|application|ami|friend|meeting|"
                             r"r[ée]union|rendez-vous|appointment|pull request|changes|modifications|connexion|access|acc[eè]s|proposition|proposal|mission|projet|project)",
                             re.I)


def commits(own):
    """Whether a control's own name commits something the user must approve (pay, send, delete, accept…)."""
    head = own.split(":")[0].strip().rstrip(".!")
    if REFUSES_SOMEONE.search(head) or re.search(r"\b(apply (for|to|now)|postuler|candidater|envoyer (ma|votre) candidature)\b", head, re.I):
        return True
    # A refusal whose description commits ("Reject: delete", "Decline: report user") still stops.
    tail = DECLINE_WORDS.sub(" ", own.split(":", 1)[1]) if ":" in own else ""
    if declines(own) and IRREVERSIBLE.search(tail):
        return True
    if (SEARCH_SUBMIT.fullmatch(head) and not PAYWALL.search(own)) or declines(own):
        return False
    return bool(IRREVERSIBLE.search(own))


def decline_instead(action, page, banner, confirm=None):
    """On a consent banner, the refusal next to the accept button Jev chose (privacy first), if there is one.

    `banner(a, b)` returns the text of the box holding both controls, or None when they are not on one banner.
    An accept the caller confirmed by name is kept."""
    if not action or action["kind"] != "click":
        return None
    own = action.get("base") or action["label"]
    if not CONSENT_ACCEPT.search(own) or (confirm and confirm.lower() in action["label"].lower()):
        return None
    for a in page["actions"]:
        name = a.get("base") or a["label"]
        if a["kind"] == "click" and declines(name):
            text = banner(action["node"], a["node"])
            if text is not None and COOKIE_STRICT.search(own + " " + text):
                return a
    # No refusal on this layer: open the banner's settings, where "Tout refuser" usually is.
    for a in page["actions"]:
        # The name before any colon or comma ("Afficher toutes les finalités, Ouvre la boîte de dialogue…").
        name = re.split(r"[:,]", a.get("base") or a["label"])[0].strip().rstrip(".!")
        if a["kind"] == "click" and a["node"] != action["node"] and len(name) <= 40 and \
                CONSENT_SETTINGS.fullmatch(name) and not commits(name):
            text = banner(action["node"], a["node"])
            if text is not None and COOKIE_STRICT.search(own + " " + text):
                return a
    return None


# The text of the box around a control: its nearest ancestor holding a paragraph, if banner-sized.
BOX_TEXT = """(node => {
  let e=window.__jevFast?.nodes.get(node)?.parentElement;
  while (e && (e.innerText||'').length<150) e=e.parentElement;
  const text=e?.innerText||''; return e && text.length<4000 ? text : null;
})"""


COOKIE_WORDS = re.compile(r"cookie|traceur|consentement|\bconsent|rgpd|gdpr", re.I)


def consent_refusal(page, box):
    """A cookie refusal to click before anything else: a control named only as a refusal ("Tout refuser", "Je
    n'accepte rien") in a box that speaks of cookies. `box(node)` returns the text of the box around a control, or
    None when that box is page-sized. "Refuser le devis" or "Decline invitation" never qualify."""
    for a in page["actions"]:
        name = a.get("base") or a["label"]
        head = re.sub(r"[\W_]+$", "", name.split(":")[0].strip())  # "Continuer sans accepter ➜": the arrow is decoration
        if a["kind"] == "click" and declines(name) and not commits(name) and \
                (DECLINE.fullmatch(head) or re.fullmatch(r"(non,? )?je (n['’]accepte (rien|pas)|pr[ée]f[èe]re refuser)", head, re.I)):
            text = box(a["node"])
            # The banner also offers to accept: a lone "Decline" in a box about cookies is not enough.
            if text is not None and COOKIE_STRICT.search(text) and CONSENT_ACCEPT.search(text):
                return a
    return None


# Controls made to be pressed again and again: steppers, pagination, calendar months.
REPEATABLE = re.compile(r"\b(next|suivant|suivante|previous|pr[ée]c[ée]dent\w*|plus|moins|more|less|add|ajouter|increase|"
                        r"decrease|augmenter|diminuer|mois|month|page|scroll|load more|voir plus|afficher plus)\b|^[+\-−›‹>< ]+$",
                        re.I)


def repeating(labels):
    """The label pressed 4 times in the last 6 actions (scrolls and waits aside), unless it is made to repeat."""
    recent = labels[-6:]
    for label in set(recent):
        if recent.count(label) >= 4 and not REPEATABLE.search(label):
            return label
    return None


# A control that closes a picker ("Done" under a calendar), and one that launches a search.
CLOSES_PICKER = re.compile(r"(done|termin[ée]|ok|apply|appliquer|listo|aplicar)\b", re.I)
# The whole name of a picker's own "Done" (picker_done clicks it without asking Jev): never "Apply" or "OK",
# which also submit forms and applications.
PICKER_DONE = re.compile(r"(done|termin[ée]|listo)", re.I)
LAUNCHES_SEARCH = re.compile(r"(search|rechercher|recherche|buscar|suchen|trouver)\b", re.I)


def picker_closed(history):
    """The last action (waits aside) closed a picker, after a value was typed."""
    while history and history[-1].get("kind") == "wait":
        history = history[:-1]
    return bool(history) and bool(CLOSES_PICKER.match(history[-1].get("action", ""))) and \
        any(h.get("kind") == "fill" for h in history)


def premature_done(history, values, typed, page, nudged):
    """Why a DONE is too early, if it is: a supplied value was never typed (the site remembered an earlier search
    and shows it), or a picker closed after a value was entered while the search it feeds was never launched."""
    # Only before any action: later, an untyped value is usually one that was clicked (a calendar day).
    if not history and [k for k in values if k not in typed] and "values" not in nudged:
        return "values", None
    while history and history[-1].get("kind") == "wait":  # waits after the picker closed change nothing
        history = history[:-1]
    if history and "search" not in nudged and CLOSES_PICKER.match(history[-1].get("action", "")):
        last_fill = max((i for i, h in enumerate(history) if h.get("kind") == "fill"), default=-1)
        if last_fill < 0:
            return None, None
        # The search is stale when something was chosen after the last search (a date picked in the picker that a
        # first "Search" opened), or when no search followed the last typed value.
        searches = [i for i, h in enumerate(history[:-1]) if LAUNCHES_SEARCH.match(h.get("action", ""))]
        launched = bool(searches) and searches[-1] > last_fill and searches[-1] == len(history) - 2
        search = next((a for a in page["actions"] if a["kind"] == "click" and
                       LAUNCHES_SEARCH.fullmatch((a.get("base") or a["label"]).strip())), None)
        if search and not launched:
            return "search", search
    return None, None


# A field that announces a list of suggestions; with `shown`, whether that list now shows options.
SUBMITS_TYPED = """((field, button) => {
  const x=window.__jevFast?.nodes.get(field), y=window.__jevFast?.nodes.get(button); if (!x?.isConnected || !y?.isConnected) return false;
  // Only a search box: a single-line input that says so (never a textarea or editor, where a nameless button may send).
  if (x.tagName !== 'INPUT') return false;
  const says=[x.type, x.getAttribute('role'), x.name, x.id, x.placeholder, x.getAttribute('aria-label')].join(' ');
  if (!/\\b(search|recherch|chercher|buscar|busca|suche|cerca|zoek)/i.test(says)) return false;
  // A search that adds someone or something (invite, share, recipient) is not a plain search.
  const near=(x.closest('form,[role="search"],[role="dialog"]')||x.parentElement)?.innerText||'';
  if (/invit|\\badd\\b|ajout|share|partag|recipient|destinataire|b[ée]n[ée]ficiaire|payee|member|membre|people|personnes?\\b|\\busers?\\b|contact/i.test(says + ' ' + near.slice(0, 400))) return false;
  const form=y.closest('form'); if (form && (form.method||'get').toLowerCase()==='post') return false;
  // The button sits next to the field: within three levels up, in a box with that one text field and no password.
  let box=x.parentElement; for (let i=1; box && i<3 && !box.contains(y); i++) box=box.parentElement;
  if (!box || !box.contains(y) || box.querySelector('input[type="password"]')) return false;
  const texts=[...box.querySelectorAll('input,textarea,[contenteditable="true"]')].filter(e => !/^(hidden|submit|button|checkbox|radio|reset|image)$/i.test(e.type||''));
  return texts.length === 1 && texts[0] === x;
})"""
SUGGESTS = """((node, shown) => {
  const e=window.__jevFast?.nodes.get(node); if (!e?.isConnected) return false;
  if (!shown) return /list|both|inline/.test(e.getAttribute('aria-autocomplete')||'') ||
    /listbox|true/.test(e.getAttribute('aria-haspopup')||'');
  return [...document.querySelectorAll('[role="option"]')].some(o => o.checkVisibility({checkOpacity:true}));
})"""
# The observed ids of the options inside the list a field controls (aria-controls / aria-owns), or null.
OWNED = """(node => {
  const c=window.__jevFast, e=c?.nodes.get(node); if (!e?.isConnected) return false;  // the field is gone
  const ids=(e.getAttribute('aria-controls')||'')+' '+(e.getAttribute('aria-owns')||'');
  const lists=ids.split(/\\s+/).filter(Boolean).map(id=>document.getElementById(id)).filter(Boolean);
  if (!lists.length) return null;
  return lists.flatMap(l=>[...l.querySelectorAll('[role="option"]')]).map(o=>c.ids.get(o)).filter(Boolean);
})"""
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
  let a = window.__jevFast?.nodes.get(node);
  if (!a?.isConnected) return false;
  for (let i = 0; i < 3 && a.parentElement; i++) a = a.parentElement;
  // Only next to the control just used: result pages keep page-wide spinners and "Loading prices." lines forever.
  // Step bars (a progressbar with a value) are not loading states.
  if ([...a.querySelectorAll('[aria-busy="true"],progress:not([value]),[role="progressbar"]:not([aria-valuenow])')]
      .some(shown) || a.closest('[aria-busy="true"]')) return true;
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


STOPWORDS = {"des", "les", "aux", "the", "and", "for", "your", "votre", "vos", "pour", "avec", "with", "del", "los",
             "las", "une", "est", "what", "quel", "quelle", "where"}


def fold(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


def names(option):
    """What a suggestion names: its first line, or its name before the first comma ("Zürich, Switzerland")."""
    return fold((option.get("first") or option.get("base") or option["label"]).split(",")[0])


MONTHS = [("jan", "janv", "janvier", "january", "ene", "enero", "januar"), ("feb", "fev", "fevr", "fevrier", "february", "febrero", "februar"),
          ("mar", "mars", "march", "marzo", "marz"), ("apr", "avr", "avril", "april", "abr", "abril"),
          ("may", "mai", "mayo"), ("jun", "juin", "june", "junio", "juni"), ("jul", "juil", "juillet", "july", "julio", "juli"),
          ("aug", "aou", "aout", "august", "ago", "agosto"), ("sep", "sept", "septembre", "september", "septiembre"),
          ("oct", "octobre", "october", "octubre", "oktober"), ("nov", "novembre", "november", "noviembre"),
          ("dec", "decembre", "december", "dic", "diciembre", "dez", "dezember")]


WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "lundi", "mardi", "mercredi",
            "jeudi", "vendredi", "samedi", "dimanche", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"}


def day_month_year(text):
    """(day, month, year or None) of the first date in a text, in words or ISO, else None. The day is the number
    right after the month ("Nov 20"), else right before it ("20 nov.")."""
    t = fold(text)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return int(m[3]), int(m[2]), int(m[1])
    words = re.findall(r"[a-z]+|\d+", t)
    day = lambda x: x.isdigit() and len(x) <= 2 and 1 <= int(x) <= 31
    for i, w in enumerate(words):
        month = next((n + 1 for n, names_ in enumerate(MONTHS) if w in names_), None)
        if not month:
            continue
        after = words[i + 1] if i + 1 < len(words) and day(words[i + 1]) else None
        before = words[i - 1] if i and day(words[i - 1]) else \
            words[i - 2] if i > 1 and words[i - 1] in WEEKDAYS and day(words[i - 2]) else None  # "22, Sunday, November"
        # "mar." is also Tuesday (mardi, martes): March only as "20 mar" or "Mar 20, 2026".
        if w == "mar" and not before and not (after and i + 2 < len(words) and len(words[i + 2]) == 4 and words[i + 2].isdigit()):
            continue
        if after or before:
            rest = words[i + 2:i + 3] if after else words[i + 1:i + 2]
            year = next((int(x) for x in rest if x.isdigit() and len(x) == 4), None)
            return int(after or before), month, year
    return None


DATE_WORDS = {w for names_ in MONTHS for w in names_} | {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "lundi", "mardi", "mercredi", "jeudi",
    "vendredi", "samedi", "dimanche", "lun", "mer", "jeu", "ven", "sam", "dim", "mon", "tue", "wed", "thu", "fri", "sat",
    "sun", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo", "euros", "euro", "eur", "usd", "chf",
    "gbp", "from", "des", "a", "partir", "de", "selected", "today", "aujourd", "hui", "departure", "return", "date", "dates"}


def date_only(label):
    """A label that is just a date, maybe with a weekday, a price and a calendar word: a day cell, not a button."""
    return all(w.isdigit() or w in DATE_WORDS for w in re.findall(r"[a-z]+|\d+", fold(label)))


def calendar_day(history, values, picked, page):
    """Right after opening a date field, the one visible day matching the value its key names (no model call).

    Only when the opened field's label names exactly one supplied date key, and exactly one control shows that
    day (same year when both say it). Anything less certain goes to Jev."""
    if not history or not history[-1].get("action", "").startswith("Open "):
        return None
    keys = [k for k in names_key(history[-1]["action"][5:], values) if k not in picked]
    want = len(keys) == 1 and day_month_year(str(values[keys[0]]))
    if not want:
        return None
    days = [a for a in page["actions"] if a["kind"] == "click" and not a.get("offscreen") and
            (a.get("role") == "gridcell" or (a.get("role") in {"button", "option", "link"} and date_only(a.get("base") or a["label"])))]
    found = []
    for a in days:
        got = day_month_year(a.get("base") or a["label"])
        if got and got[:2] == want[:2] and (not got[2] or not want[2] or got[2] == want[2]):
            found.append(a)
    return (keys[0], found[0]) if len({a["node"] for a in found}) == 1 else None


def range_day(values, typed, picked, page):
    """In an open month grid (20 day cells or more), the next day of a supplied date range to click, in date order:
    arrival first, then departure, whatever the grid already shows (sites remember an earlier search). Only for
    exactly two supplied dates, neither typed; the day must be shown by exactly one cell."""
    dates = [k for k in values if day_month_year(str(values[k]))]
    if len(dates) != 2 or any(k in typed for k in dates):
        return None
    cells = [a for a in page["actions"] if a["kind"] == "click" and not a.get("offscreen") and
             not a["label"].startswith("Open ") and day_month_year(a.get("base") or a["label"])]
    # The grid's cells share one role; a summary button ("Choisir des dates. ven. 20 nov. — ven. 27 nov.") does not.
    roles = [a.get("role") for a in cells]
    cells = [a for a in cells if a.get("role") == max(set(roles), key=roles.count)] if cells else []
    if len({a["node"] for a in cells}) < 20:
        return None
    order = sorted(dates, key=lambda k: (lambda d: (d[2] or 0, d[1], d[0]))(day_month_year(str(values[k]))))
    for k in order:
        if k in picked:
            continue
        want = day_month_year(str(values[k]))
        found = [a for a in cells if (lambda got: got[:2] == want[:2] and (not got[2] or not want[2] or got[2] == want[2]))(
            day_month_year(a.get("base") or a["label"]))]
        if found:
            return (k, found[0]) if len({a["node"] for a in found}) == 1 else None
        # The grid shows other months (the site kept an earlier search): step toward the wanted month, six times at most.
        dates_shown = [day_month_year(a.get("base") or a["label"]) for a in cells]
        steps = sum(1 for p in picked if str(p).startswith("month:"))
        if steps >= 6:
            return None
        if want[2] and all(d[2] for d in dates_shown):  # years on both sides: compare (year, month)
            shown = sorted({(d[2], d[1]) for d in dates_shown})
            goal = (want[2], want[1])
            if shown[0] <= goal <= shown[-1]:
                return None
            back = goal < shown[0]
        else:  # no years: the shorter way round the twelve months, forward on a tie
            months = {d[1] for d in dates_shown}
            if want[1] in months:
                return None
            ahead = min((want[1] - m) % 12 for m in months)
            back = 12 - max((want[1] - m) % 12 for m in months) < ahead
        way = MONTH_BACK if back else MONTH_ON
        nav = [a for a in page["actions"] if a["kind"] == "click" and not a.get("offscreen") and
               way.search(a.get("base") or a["label"])]
        return (f"month:{steps}", nav[0]) if len({a["label"] for a in nav}) == 1 else None
    return None


MONTH_BACK = re.compile(r"\bmois (précédent|precedent)\b|\bprevious month\b", re.I)
MONTH_ON = re.compile(r"\bmois (suivant|prochain)\b|\bnext month\b", re.I)


def picker_done(history, values, typed, picked, page):
    """Right after a day was clicked, the picker's one "Done" control, when every supplied date is now entered."""
    last = history[-1].get("action", "") if history else ""
    if not history or history[-1].get("kind") != "click" or not day_month_year(last) or not date_only(last):
        return None
    dates = [k for k in values if day_month_year(str(values[k]))]
    if not dates or any(k not in typed and k not in picked for k in dates):
        return None
    done = [a for a in page["actions"] if a["kind"] == "click" and not a.get("offscreen") and
            PICKER_DONE.fullmatch((a.get("base") or a["label"]).strip().rstrip(".!")) and not commits(a.get("base") or a["label"])]
    return done[0] if len({a["node"] for a in done}) == 1 else None


def echoed(page, lines_before, typed):
    """Whether a new line on the page, outside the suggestions, repeats the typed query (results shown in place)."""
    want = fold(typed or "")
    options = {fold(a["label"]) for a in page["actions"] if a.get("role") == "option"}
    return bool(want) and any(want in fold(line) and fold(line) not in options
                              for line in set(page.get("text", "").splitlines()) - lines_before)


def exact_suggestion(typed, page, owned=None):
    """The one suggestion naming exactly the typed text (accents and case aside)."""
    if not typed or owned is False:
        return None
    want = fold(typed)
    found = [a for a in page["actions"] if a["kind"] == "click" and a.get("role") == "option" and
             (owned is None or a["node"] in owned) and names(a) == want]
    # Several suggestions naming it ("Paris, France", "Paris, Texas"): the goal decides, so Jev does.
    return found[0] if len({a["node"] for a in found}) == 1 else None


def suggestion_for(typed, action, page, owned=None, exact=False):
    """Right after typing into a field with suggestions, the suggestion Jev skipped when it moved on.

    Many sites (Doctolib, Maps, booking engines) ignore free text until a suggestion is chosen. When Jev's next
    choice leaves the field without choosing, take the suggestion equal to the typed text, else the first that
    starts with it, else the first holding it as a word. `owned` limits the choice to the field's own list;
    `exact` (Jev chose to launch a search) keeps only an equal one, so a site search runs on what was typed."""
    if not typed or owned is False or (action and action.get("role") == "option"):
        return None
    want = fold(typed)
    options = [a for a in page["actions"] if a["kind"] == "click" and a.get("role") == "option" and
               (owned is None or a["node"] in owned)]
    found = next((a for a in options if names(a) == want or fold(a.get("base") or a["label"]) == want), None)
    if found or exact:
        return found
    for test in (lambda t: t.startswith(want), lambda t: re.search(r"\b" + re.escape(want), t)):
        found = next((a for a in options if test(fold(a.get("base") or a["label"]))), None)
        if found:
            return found
    return None


def names_key(label, values):
    """The supplied keys whose words name a field label ("from" in "Where from?"), by the rule value_chooser uses."""
    label_words = set(re.findall(r"\w+", fold(label)))
    meaningful = {w for w in label_words if len(w) > 2 and w not in STOPWORDS}
    return [k for k in values if (lambda kw: kw <= label_words or (meaningful and meaningful <= kw))(
        set(re.findall(r"\w+", fold(key_words(k)))))]


# A date value: typed into a date field it often fights the field's own calendar, so Jev and the picker handle it.
DATE_VALUE = re.compile(r"\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}|\b(jan|feb|f[ée]v|mar|apr|avr|may|mai|jun|juin|jul|juil|aug|ao[uû]|"
                        r"sep|oct|nov|dec|d[ée]c)\w*\.?\s*\d|\d\s*(jan|feb|f[ée]v|mar|apr|avr|may|mai|jun|juin|jul|juil|aug|"
                        r"ao[uû]|sep|oct|nov|dec|d[ée]c)", re.I)


FIELD_WORDS = {"code", "numero", "number", "no", "num", "votre", "your", "saisir", "enter", "indiquez", "e"}


def direct_fill(values, typed, page, done):
    """A field to fill without asking Jev: the one visible text field a supplied, not yet typed key names, and the
    only key naming it. `done` holds the keys already filled this way (once each)."""
    fields = [a for a in page["actions"] if a["kind"] == "fill" and a.get("role") in {"textbox", "combobox", "searchbox"}]

    def whole(label, k):  # the key names the whole label ("from" ↔ "Where from?"), not a part ("name" ↔ "Company name")
        # Hints in brackets ("(14 chiffres)"), digits and field-type words ("Code APE") do not name anything else.
        words = {w for w in re.findall(r"[a-z]+", fold(re.sub(r"\([^)]*\)", " ", label)))} - STOPWORDS - FIELD_WORDS
        return bool(words) and words <= set(re.findall(r"\w+", fold(key_words(k))))

    for k in values:
        if k in typed or k in done or DATE_VALUE.search(str(values[k])):
            continue
        # The label Jev and value_chooser read (row text included when two controls share a name).
        hits = [a for a in fields if names_key(a["label"], values) == [k] and whole(a["label"], k)]
        if len({a["node"] for a in hits}) == 1 and fold(hits[0].get("value") or "") != fold(str(values[k])):
            return k, hits[0]
    return None


def value_chooser(values, typed):
    """Jev picks a key from the caller's values; a field without a matching value stops the run."""

    def text_fn(context):
        field = context["field"]["label"]
        if not values:
            raise Stop("need_value", field=field)
        # When exactly one key names the field ("from" in "Where from?", "departure" in "Departure"), take it
        # without a model call; ambiguous or indirect labels still go to Jev.
        label_words = set(re.findall(r"\w+", fold(field)))
        meaningful = {w for w in label_words if len(w) > 2 and w not in STOPWORDS}
        named = [k for k in values if (lambda kw: kw <= label_words or (meaningful and meaningful <= kw))(
            set(re.findall(r"\w+", fold(key_words(k)))))]
        if len(named) == 1:
            return values[named[0]], {"model": f"values:{named[0]}", "latency_ms": 0, "usage": {}}
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
    browser.commits = commits  # fresh() refuses a control whose name grew into a committing one
    # Refuse to type when the click left focus on a credential field (e.g. a login modal opened).
    browser.focus_guard = ("(() => {" + CREDENTIAL_JS + " let a = document.activeElement;"
                           " while (a?.shadowRoot?.activeElement) a = a.shadowRoot.activeElement;"
                           " if (a?.tagName === 'IFRAME') return false;"  # an embedded form we cannot inspect, often a login
                           " return !a || a.tagName !== 'INPUT' || !isCredential(a); })()")
    state["history"] = saved.get("history", [])
    status, info, logins, empty_waits, done_waits, last_node = None, {}, 0, 0, 0, None
    goal, nudged, nudged_consent, directed, picked_days, banned = state["goal"], set(), 0, set(), set(), set()
    last_fill = None
    cycle, auto_scrolls, stale, unsure_waits, just_typed, replays, pressed = [], 0, 0, 0, None, {}, []
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
                # Suggestions fetched over the network land after the read that follows typing (Doctolib: 0.3 s):
                # on a field that announces a list, wait for them (0.8 s at most) before deciding.
                if just_typed and not just_typed[2] and \
                        not any(a.get("role") == "option" for a in state["page"]["actions"]) and \
                        browser.evaluate(f"{SUGGESTS}({just_typed[0]})"):
                    until = time.monotonic() + 0.8
                    while time.monotonic() < until and not browser.evaluate(f"{SUGGESTS}({just_typed[0]}, true)"):
                        time.sleep(0.1)
                    state["page"] = browser.observe(screenshot=False)
                # Typed "Zurich" and the list offers "Zürich, Switzerland": the suggestion naming exactly what was
                # typed (before its comma) needs no model call. Anything less certain goes to Jev.
                # A cookie banner with a refusal on it: refuse first, without a model call (privacy, and Jev tends
                # to wait in front of a consent layer). Twice at most: some banners have a second layer.
                refusal = nudged_consent < 2 and consent_refusal(state["page"], lambda n: browser.evaluate(f"{BOX_TEXT}({n})"))
                if refusal:
                    nudged_consent += 1
                    if state["started_at"] is None:  # the clock starts at the first decision, model or not
                        state["started_at"] = time.perf_counter()
                    state["decision"], state["status"] = {
                        "choice": refusal["id"], "operation": "CLICK", "target": None, "confidence": 1.0,
                        "probabilities": {refusal["id"]: 1.0}, "latency_ms": 0, "usage": {}}, "predicted"
                pick = not refusal and just_typed and not just_typed[2] and exact_suggestion(
                    just_typed[1], state["page"], browser.evaluate(f"{OWNED}({just_typed[0]})"))
                direct = not refusal and not pick and not just_typed and direct_fill(values, typed, state["page"], directed)
                if direct:
                    directed.add(direct[0])
                    if state["started_at"] is None:
                        state["started_at"] = time.perf_counter()
                    state["decision"], state["status"] = {
                        "choice": direct[1]["id"], "operation": "TYPE_TEXT", "target": None, "confidence": 1.0,
                        "probabilities": {direct[1]["id"]: 1.0}, "latency_ms": 0, "usage": {}}, "predicted"
                day = not refusal and not pick and not direct and (
                    calendar_day(state["history"], values, picked_days, state["page"]) or
                    range_day(values, typed, picked_days, state["page"]))
                if day:
                    picked_days.add(day[0])
                elif not refusal and not pick and not direct and "picker_done" not in nudged:
                    close = picker_done(state["history"], values, typed, picked_days, state["page"])
                    if close:
                        nudged.add("picker_done")
                        day = (None, close)
                if day:
                    state["decision"], state["status"] = {
                        "choice": day[1]["id"], "operation": "CLICK", "target": None, "confidence": 1.0,
                        "probabilities": {day[1]["id"]: 1.0}, "latency_ms": 0, "usage": {}}, "predicted"
                if refusal or direct or day:
                    pass
                elif pick:
                    state["decision"], state["status"] = {
                        "choice": pick["id"], "operation": "CLICK", "target": None, "confidence": 1.0,
                        "probabilities": {pick["id"]: 1.0}, "latency_ms": 0, "usage": {}}, "predicted"
                else:
                    agent.banned = banned
                    agent.command("predict")
                decision = state["decision"]
                # An unsure BLOCKED right after an action is usually a page still working (a dialog submitting, a
                # list loading): wait and look again before giving up.
                if decision["choice"] == "BLOCKED" and decision.get("confidence", 1) < 0.6 and unsure_waits < 6:
                    unsure_waits += 1
                    time.sleep(0.4)
                    decision["choice"] = "wait"
                    decision["probabilities"] = {**decision.get("probabilities", {}), "wait": 0.0}
                # Jev tends to answer BLOCKED when the target sits below the visible area. While the page or its
                # panel can still scroll, look further before giving up.
                if decision["choice"] == "BLOCKED" and auto_scrolls < 8 and \
                        any(a["id"] == "scroll_down" for a in state["page"]["actions"]):
                    auto_scrolls += 1
                    decision["choice"] = "scroll_down"
                    decision["probabilities"] = {**decision.get("probabilities", {}), "scroll_down": 0.0}
                # A DONE, or a wait, right after a picker closed (its "Done" reads like a search) is premature
                # while the search it feeds was never launched.
                if decision["choice"] in {"DONE", "wait"}:
                    why, search = premature_done(state["history"], values, typed, state["page"], nudged)
                    # Right after a picker closed, its search button may still be hidden by the closing dialog:
                    # look again for up to 0.6 s instead of paying a model call for a wait.
                    if why is None and not {"search", "look"} & nudged and picker_closed(state["history"]):
                        nudged.add("look")
                        until = time.monotonic() + 0.6
                        while why is None and time.monotonic() < until:
                            time.sleep(0.1)
                            state["page"] = browser.observe(screenshot=False)
                            why, search = premature_done(state["history"], values, typed, state["page"], nudged)
                        if why is None:  # the page changed under the decision: ask again on what is there now
                            state["decision"], state["status"] = None, "ready"
                            continue
                    # A DONE right after launching a search judges the page before the results: wait for the
                    # update in the page once, then ask again.
                    if why is None and decision["choice"] == "DONE" and "results" not in nudged and \
                            state["history"] and LAUNCHES_SEARCH.match(state["history"][-1].get("action", "")):
                        nudged.add("results")
                        browser.act({"id": "wait", "kind": "wait"}, state["page"])
                        state["page"] = browser.observe(screenshot=False)
                        state["decision"], state["status"] = None, "ready"
                        continue
                    # Days picked in a calendar this run, and no search since: the results do not use them yet.
                    if why is None and decision["choice"] == "DONE" and "after_days" not in nudged and \
                            any(not str(p).startswith("month:") for p in picked_days):
                        clicks = [i for i, h in enumerate(state["history"]) if h.get("kind") == "click"]
                        days = [i for i in clicks if day_month_year(state["history"][i].get("action", ""))]
                        launched = [i for i in clicks if LAUNCHES_SEARCH.match(state["history"][i].get("action", ""))]
                        go = next((a for a in state["page"]["actions"] if a["kind"] == "click" and not a.get("offscreen")
                                   and LAUNCHES_SEARCH.fullmatch((a.get("base") or a["label"]).strip())), None)
                        if days and (not launched or launched[-1] < days[-1]) and go:
                            nudged.add("after_days")
                            why, search = "search", go
                    if why == "values" and decision["choice"] == "DONE":  # say so in the goal Jev reads, and ask again (once: a date may be clicked)
                        nudged.add(why)
                        state["goal"] = goal + " Not entered yet in this run: " + \
                            ", ".join(f"{k} {values[k]}" for k in values if k not in typed) + "."
                        state["decision"], state["status"] = None, "ready"
                        continue
                    if why == "search":  # launch the search the closed picker was filling
                        nudged.add(why)
                        decision["choice"] = search["id"]
                        decision["probabilities"] = {**decision.get("probabilities", {}), search["id"]: 0.0}
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
                swap = decline_instead(action, state["page"],
                                       lambda a, b: browser.evaluate(f"{SHARED_BOX}({a}, {b})"), confirm)
                carry = None
                if just_typed and not swap and decision["choice"] not in {"DONE", "BLOCKED", "wait"} and \
                        (action or {}).get("role") != "option":
                    node, text, relaxed = just_typed
                    # Launching a search right after typing searches what was typed: only an equal suggestion is
                    # taken. If the search then leaves the page where it was, the site wanted a suggestion.
                    exact = not relaxed and bool(action and action["kind"] == "click" and
                                                 LAUNCHES_SEARCH.fullmatch((action.get("base") or action["label"]).strip()))
                    swap = suggestion_for(text, action, state["page"], browser.evaluate(f"{OWNED}({node})"), exact)
                    if exact and not swap:
                        carry = (node, text, state["page"]["url"])
                    # Suggestions fetched over the network can land after the page was read: wait for them (1.5 s
                    # at most, only on a field that announces a list), then choose on the page that has them.
                    elif not swap and browser.evaluate(f"{SUGGESTS}({node})"):
                        until = time.monotonic() + 1.5
                        while time.monotonic() < until and not browser.evaluate(f"{SUGGESTS}({node}, true)"):
                            time.sleep(0.1)
                        state["page"] = browser.observe(screenshot=False)
                        swap = suggestion_for(text, None, state["page"], browser.evaluate(f"{OWNED}({node})"))
                        if not swap:
                            just_typed, state["decision"], state["status"] = None, None, "ready"
                            continue
                if decision["choice"] != "wait":  # a wait keeps the typed text for when suggestions arrive
                    just_typed = None
                if swap:
                    action, decision["choice"] = swap, swap["id"]
                    decision["probabilities"] = {**decision.get("probabilities", {}), swap["id"]: 0.0}
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
                    ((action or {}).get("named") is False or not re.search(r"[^\W_]", own)) and not (action or {}).get("menu")
                # A nameless button that submits the search form just typed into (no password, one text field,
                # not a POST form) only launches that search.
                if generic and action and action["kind"] == "click" and last_fill is not None and not commits(label) and \
                        browser.evaluate(f"{SUBMITS_TYPED}({json.dumps(last_fill)}, {json.dumps(action['node'])})"):
                    generic = False
                if action and action["kind"] in {"click", "select"} and (commits(own) or generic):
                    if not (confirm and confirm.lower() in label.lower()):
                        # A cookie wall that only offers "accept" or "pay": say so, the caller asks the user which.
                        box = CONSENT_ACCEPT.search(own) and browser.evaluate(f"{BOX_TEXT}({json.dumps(action['node'])})")
                        if box and COOKIE_WORDS.search(box) and PAYWALL.search(box):
                            raise Stop("confirm", action=label, reason="consent_or_pay")
                        raise Stop("confirm", action=label)
                steps, before, url_before = len(state["history"]), state["page"]["fingerprint"], state["page"]["url"]
                lines_before = set(state["page"].get("text", "").splitlines())
                browser.strict = bool(action and action["kind"] in {"click", "select"} and (commits(own) or generic))
                try:
                    agent.command("act", {"fingerprint": state["page"]["fingerprint"]})
                except ValueError as e:
                    if "No single option" in str(e) or "not a number" in str(e):  # the value fits no list or counter
                        raise Stop("need_value", field=label, reason=str(e)) from None
                    raise
                finally:
                    # One irreversible click per --confirm, spent as soon as the click is recorded (even if the
                    # page then navigates and the next read goes stale).
                    if len(state["history"]) > steps and action and confirm and confirm.lower() in label.lower() and \
                            (commits(own) or generic):
                        confirm = None
                if action and len(state["history"]) > steps:  # only right after typing
                    last_fill = action["node"] if action["kind"] == "fill" else None
                if action and action["kind"] == "click":
                    last_node = action["node"]
                    # A search launched right after typing that changed nothing: some sites (Google Maps) ignore it
                    # until their own suggestions have loaded. Click it again, up to three times, without Jev.
                    if len(state["history"]) > steps and "relaunch" not in nudged and \
                            LAUNCHES_SEARCH.fullmatch(own.strip()) and state["history"][-2:-1] and \
                            state["history"][-2].get("kind") == "fill" and state["page"]["url"] == url_before and \
                            carry and not echoed(state["page"], lines_before, carry[1]):
                        # Typed into a field with suggestions, then searched without picking one, and no new line
                        # repeats the query ("12 recettes pour ratatouille"): the search did not run.
                        nudged.add("relaunch")
                        for _ in range(3):  # 0.8 s apart, until the page leaves or shows the results
                            time.sleep(0.8)
                            state["page"] = browser.observe(screenshot=False)
                            if state["page"]["url"] != url_before or echoed(state["page"], lines_before, carry[1]):
                                break
                            same = [a for a in state["page"]["actions"] if a["kind"] == "click" and
                                    (a.get("base") or a["label"]) == own]
                            again = next((a for a in same if a["node"] == action["node"]), same[0] if same else None)
                            if not again:
                                break
                            try:
                                browser.act(again, state["page"])
                            except Exception:  # noqa: BLE001 - the click Jev chose already ran; stop retrying
                                break
                        state["page"] = browser.observe(screenshot=False)
                if action and action["kind"] == "fill" and action.get("role") in {"combobox", "searchbox"} and \
                        len(state["history"]) > steps:
                    just_typed = (action["node"], state["history"][-1].get("text"), False)
                elif carry and len(state["history"]) > steps and state["page"]["url"] == carry[2]:
                    just_typed = (*carry[:2], True)
                stale = 0
                state["goal"] = goal
                helper = (state["history"][-1].get("text_helper") or "") if len(state["history"]) > steps else ""
                if helper.startswith("values:"):  # count a value only once it was actually typed
                    typed.append(helper[len("values:"):])
                # Jev can cycle between two page states (a menu opening and closing), which the upstream no-change
                # check misses: stop after 9 actions cycling over at most 3 labels and 3 page states instead of running to the step cap. Steppers, pagination
                # and date pickers repeat a label too, but each click reaches a new page state, so they pass.
                if action and action["kind"] not in {"scroll", "wait"}:
                    # Longer cycles (a date range picked in the wrong order, then searched, again and again) visit
                    # more states, but each pass replays the same action from the same page: three times is a loop.
                    key = (label, before)
                    replays[key] = replays.get(key, 0) + 1
                    if replays[key] >= 3:
                        if banned or label in banned:  # a second loop: stop
                            raise Stop("blocked", reason="loop", actions=[label])
                        banned.add(label)  # a first loop: hide that control from Jev and let it try another way
                    # A search launched a third time is not progressing either, even when the page differs a
                    # little on each pass (Booking: dates picked in the wrong order, then searched again).
                    if action["kind"] == "click" and LAUNCHES_SEARCH.fullmatch(own.strip()):
                        replays[("search", own.strip().lower())] = searches = \
                            replays.get(("search", own.strip().lower()), 0) + 1
                        if searches >= 3:
                            raise Stop("blocked", reason="loop", actions=[label])
                    pressed.append(label)
                    if repeating(pressed):  # the same control again and again, each time on a slightly new page
                        if banned:  # a second loop: stop
                            raise Stop("blocked", reason="loop", actions=[label])
                        banned.add(label)  # a first loop: hide that control from Jev and let it try another way
                        pressed.clear()
                    cycle = (cycle + [key])[-9:]
                    if len(cycle) == 9 and len({c[0] for c in cycle}) <= 3 and len({c[1] for c in cycle}) <= 3:
                        raise Stop("blocked", reason="loop", actions=sorted({c[0] for c in cycle}))
            except StalePage:
                stale += 1
                if stale >= 6:  # the chosen target keeps failing its pre-input check (covered, moving, disabled)
                    raise Stop("blocked", reason="unreachable") from None
                state["decision"], state["status"] = None, "ready"
                time.sleep(0.05)
                try:
                    state["page"] = browser.observe(screenshot=False)
                except StalePage:
                    pass
    except Stop as stop:
        status, info = stop.status, stop.info
    except Exception as e:  # noqa: BLE001 - keep the target and state so the caller can resume
        status, info = "error", {"error": f"{type(e).__name__}: {e}"}
        if os.environ.get("JEVNAV_TRACE"):
            import traceback; traceback.print_exc()
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
    except AllowNeeded as e:
        result = {"status": "allow_needed", "reason": str(e)}
    except Exception as e:  # noqa: BLE001 - the caller needs a JSON status, not a traceback
        result = {"status": "error", "error": f"{type(e).__name__}: {e}"}
    log(args, result)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["status"] in {"done", "confirm", "need_value", "in_progress"} else 1)


if __name__ == "__main__":
    main()
