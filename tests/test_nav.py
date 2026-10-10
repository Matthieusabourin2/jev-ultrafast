import pytest

from jev_ultrafast import nav


@pytest.mark.parametrize("label", ["Delete", "Pay now", "Payment", "Book now", "Réserver", "Submit", "Accept all",
                                   "Sign up", "Envoyer", "Eliminar", "Confirm order", "Valider ma commande",
                                   "Supprimer le projet", "Cancel subscription", "Annuler mon abonnement", "Résilier",
                                   "Payer", "Déclarer", "Autoriser l'accès", "Publier", "Se déconnecter", "Log out",
                                   "Reserve now", "Payez", "Passer commande", "Complete booking", "Finalizar compra",
                                   "Partager", "Share", "Invite", "Create account", "Créer un compte", "Register",
                                   "Envoyez", "Supprimez", "Refuser et s'abonner", "Supprimer la recherche",
                                   "Accepter & Fermer: Accepter notre traitement des données et fermer",
                                   "Envoyer la recherche à un ami", "Envoyer ma requête", "Submit your query",
                                   "Envoyer la requête au service client"])
def test_irreversible_labels_stop(label):
    assert nav.commits(label)


@pytest.mark.parametrize("label", ["Search", "Done", "Where from?", "Sign in", "Bookmarks", "One way", "Iniciar sesión",
                                   "Pays", "Paysage", "Enregistrer", "Save", "Mettre à jour", "Modifier", "Archiver",
                                   "Annuler", "Cancel", "Ajouter", "Renommer", "Mes commandes", "Réservations",
                                   "Soumettre la recherche", "Submit search", "Continuer sans accepter", "Tout refuser",
                                   "Reject all", "Refuser", "Only necessary cookies"])
def test_navigation_labels_pass(label):
    assert not nav.commits(label)


def test_consent_accept_is_swapped_for_the_refusal():
    page = {"text": "Nous utilisons des cookies.", "actions": [
        {"id": "e1", "node": 1, "kind": "click", "label": "Accepter & Fermer: Accepter notre traitement des données et fermer"},
        {"id": "e2", "node": 2, "kind": "click", "label": "Continuer sans accepter"}]}
    banner = lambda a, b: "Nous utilisons des cookies. Accepter & Fermer Continuer sans accepter"
    assert nav.decline_instead(page["actions"][0], page, banner)["id"] == "e2"
    # The caller confirmed this very accept: keep it.
    assert nav.decline_instead(page["actions"][0], page, banner, confirm="Accepter & Fermer") is None
    # No refusal on the banner (or only a paid one): no swap, the accept still asks for confirmation.
    page["actions"][1]["label"] = "Refuser et s'abonner"
    assert nav.decline_instead(page["actions"][0], page, banner) is None


def test_invitation_decline_is_not_a_cookie_refusal():
    page = {"text": "Politique de confidentialité", "actions": [
        {"id": "e1", "node": 1, "kind": "click", "label": "Accept"},
        {"id": "e2", "node": 2, "kind": "click", "label": "Decline"}]}
    # The two buttons share an invitation card, not a consent banner; or no banner-sized box holds both.
    assert nav.decline_instead(page["actions"][0], page, lambda a, b: "Réunion jeudi 10 h. Accept Decline") is None
    assert nav.decline_instead(page["actions"][0], page, lambda a, b: None) is None


@pytest.mark.parametrize("key", ["password", "code", "username", "login", "otp", "card_number", "usuario", "pin"])
def test_secret_keys_refused(key):
    assert nav.secret_key(key)


@pytest.mark.parametrize("key", ["from", "to", "departure_date", "query", "passengers", "postal", "review", "email", "recipient", "siret"])
def test_plain_keys_allowed(key):
    assert not nav.secret_key(key)


def test_missing_values_stop_before_any_model_call():
    with pytest.raises(nav.Stop) as stop:
        nav.value_chooser({}, [])({"goal": "g", "field": {"label": "City"}, "page": {}, "recent_actions": []})
    assert stop.value.status == "need_value" and stop.value.info == {"field": "City"}


def test_journal_keeps_no_values_or_page_text(tmp_path, monkeypatch):
    monkeypatch.setattr(nav, "JOURNAL_DIR", tmp_path)
    args = type("A", (), {"url": "https://user:pw@fr.wikipedia.org/wiki/Zurich?q=secret#frag", "target": None})()
    nav.log(args, {"status": "done", "steps": 2, "elapsed_s": 3.1, "text": "page body", "actions": ["fill ← 'Zurich'"]})
    line = next(tmp_path.iterdir()).read_text()
    assert '"domain": "fr.wikipedia.org"' in line
    assert not any(x in line for x in ("Zurich", "page body", "user", "pw", "secret", "frag"))


def test_post_json_retries_unreadable_and_server_errors(monkeypatch):
    import httpx
    from jev_ultrafast import model

    answers = [httpx.Response(500), httpx.Response(200, content=b""), httpx.Response(200, json={"ok": 1})]
    monkeypatch.setattr(model.CLIENT, "post", lambda *a, **k: answers.pop(0))
    monkeypatch.setattr(model.time, "sleep", lambda s: None)
    assert model.post_json("u", "k", {}) == {"ok": 1}


@pytest.mark.parametrize("key", ["sms_code", "otpCode", "card-number", "user_name", "verificationCode"])
def test_secret_keys_refused_after_word_split(key):
    assert nav.secret_key(key)


@pytest.mark.parametrize("key", ["postal_code", "promoCode", "code_ape", "client_code", "zip-code"])
def test_ordinary_code_keys_allowed(key):
    assert not nav.secret_key(key)


def test_value_named_by_the_field_needs_no_model_call(monkeypatch):
    monkeypatch.setattr(nav, "post_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    choose = nav.value_chooser({"from": "Zurich", "to": "London", "departure_date": "Nov 20"}, [])
    for label, value in [("Where from?", "Zurich"), ("Where to? ", "London"), ("Departure", "Nov 20")]:
        assert choose({"goal": "g", "field": {"label": label}, "page": {}, "recent_actions": []})[0] == value


def test_shared_small_word_does_not_name_a_field(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    calls = []
    monkeypatch.setattr(nav, "post_json", lambda *a, **k: calls.append(1) or {"answers": {"value": {
        "type": "choice", "choice": "NONE", "confidence": 0.9,
        "probabilities": {"date_de_depart": 0.0, "destination": 0.0, "NONE": 1.0}}}})
    choose = nav.value_chooser({"date_de_depart": "12/11", "destination": "Lyon"}, [])
    for label in ("Ville de départ", "Nom de famille"):
        with pytest.raises(nav.Stop):
            choose({"goal": "g", "field": {"label": label}, "page": {}, "recent_actions": []})
    assert len(calls) == 2


def test_ambiguous_field_still_asks_the_model(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    calls = []
    monkeypatch.setattr(nav, "post_json", lambda *a, **k: calls.append(1) or {"answers": {"value": {
        "type": "choice", "choice": "to", "confidence": 0.9, "probabilities": {"from": 0.05, "to": 0.9, "NONE": 0.05}}}})
    choose = nav.value_chooser({"from": "Zurich", "to": "London"}, [])
    assert choose({"goal": "g", "field": {"label": "Where else?"}, "page": {}, "recent_actions": []})[0] == "London"
    assert calls


def test_skipped_suggestion_is_chosen():
    page = {"actions": [
        {"id": "e1", "node": 1, "kind": "click", "role": "option", "label": "Chirurgien dermatologique"},
        {"id": "e2", "node": 2, "kind": "click", "role": "option", "label": "Dermatologue et vénérologue"},
        {"id": "e3", "kind": "fill", "role": "combobox", "label": "Où ?"}]}
    assert nav.suggestion_for("dermatologue", page["actions"][2], page)["id"] == "e2"
    # Jev chose an option itself, or nothing was typed, or no suggestion holds the text: leave its choice alone.
    assert nav.suggestion_for("dermatologue", page["actions"][0], page) is None
    assert nav.suggestion_for(None, page["actions"][2], page) is None
    assert nav.suggestion_for("cardiologue", page["actions"][2], page) is None
    # Only the field's own list counts; launching a search keeps only an equal suggestion.
    assert nav.suggestion_for("dermatologue", page["actions"][2], page, owned=[]) is None
    assert nav.suggestion_for("dermatologue", page["actions"][2], page, exact=True) is None


def test_exact_suggestion_beats_a_longer_one():
    page = {"actions": [{"id": "e1", "kind": "click", "role": "option", "label": "Paris Beauvais"},
                        {"id": "e2", "kind": "click", "role": "option", "label": "Paris"}]}
    assert nav.suggestion_for("Paris", None, page)["id"] == "e2"


def test_premature_done():
    page = {"actions": [{"id": "e1", "kind": "click", "label": "Search"}]}
    assert nav.premature_done([], {"city": "Lyon"}, [], page, set())[0] == "values"
    assert nav.premature_done([], {"city": "Lyon"}, ["city"], page, set())[0] is None
    assert nav.premature_done([], {"city": "Lyon"}, [], page, {"values"})[0] is None
    history = [{"action": "Where to?", "kind": "fill"}, {"action": "Done", "kind": "click"}]
    assert nav.premature_done(history, {}, [], page, set()) == ("search", page["actions"][0])
    history.insert(1, {"action": "Search", "kind": "click"})
    assert nav.premature_done(history, {}, [], page, set())[0] is None
    assert nav.premature_done(history[:1] + history[2:], {}, [], page, {"search"})[0] is None
    # A first "Search" opened the picker, a date was picked, the picker closed: that search is stale.
    stale = [{"action": "Where to?", "kind": "fill"}, {"action": "Search", "kind": "click"},
             {"action": "Friday, November 20, 2026", "kind": "click"}, {"action": "Done. Search for flights", "kind": "click"}]
    assert nav.premature_done(stale, {}, [], page, set()) == ("search", page["actions"][0])
    assert nav.premature_done(stale + [{"action": "Wait for the page to update", "kind": "wait"}], {}, [], page,
                              set()) == ("search", page["actions"][0])
    # Closing a popup on a read-only goal (nothing typed) does not launch the site search.
    assert nav.premature_done([{"action": "OK", "kind": "click"}], {}, [], page, set())[0] is None


def test_same_target_tolerates_a_growing_name_only():
    from jev_ultrafast.browser import same_target
    g = [7, "button", "Friday, November 20, 2026", None, None, None, None, False, None, None, None, None, None, ""]
    assert same_target([*g[:2], "Friday, November 20, 2026 , 68 euros", *g[3:]], g)
    assert same_target([*g[:2], "Friday, November 20, 2026 , 68 euros", *g[3:13], "20\n€68"],
                       [*g[:2], "Friday, November 20, 2026 ????", *g[3:13], "20\n????"])
    assert not same_target([*g[:2], "Select flight 11:00", *g[3:]], [*g[:2], "Select flight 10:00", *g[3:]])
    assert not same_target([*g[:2], "Saturday, November 21, 2026", *g[3:]], g)
    assert not same_target([*g[:2], "Delete", *g[3:]], [*g[:2], "", *g[3:]])
    assert not same_target([*g[:13], "row of another item"], g)
    # A name may only grow by a price after a separator; a row may only change its prices.
    assert not same_target([*g[:2], "23", *g[3:]], [*g[:2], "2", *g[3:]])
    assert not same_target([*g[:2], "Continue and pay", *g[3:]], [*g[:2], "Continue", *g[3:]])
    assert not same_target([*g[:2], "Paris", *g[3:]], [*g[:2], "Paris Beauvais (BVA)", *g[3:]])
    assert not same_target([*g[:13], "09:40 Lyon 39 EUR Select"], [*g[:13], "08:05 Lyon 45 EUR Select"])
    assert same_target([*g[:13], "08:05 Lyon 39 EUR Select"], [*g[:13], "08:05 Lyon 45 EUR Select"])


def test_exact_suggestion_needs_no_model_call():
    page = {"actions": [{"id": "e1", "node": 1, "kind": "click", "role": "option", "label": "Zürich, Switzerland"},
                        {"id": "e2", "node": 2, "kind": "click", "role": "option", "label": "iphone 15 pro max coque"}]}
    assert nav.exact_suggestion("Zurich", page)["id"] == "e1"
    assert nav.exact_suggestion("iphone", page) is None
    assert nav.exact_suggestion("Zurich", page, owned=[2]) is None


def test_suggestion_named_on_its_first_line():
    page = {"actions": [{"id": "e1", "node": 1, "kind": "click", "role": "option", "label": "Montpellier France",
                         "first": "Montpellier"}]}
    assert nav.exact_suggestion("Montpellier", page)["id"] == "e1"
    assert nav.suggestion_for("Montpellier", None, page, exact=True)["id"] == "e1"


def test_two_suggestions_naming_it_go_to_the_model():
    page = {"actions": [{"id": "e1", "node": 1, "kind": "click", "role": "option", "label": "Paris, France"},
                        {"id": "e2", "node": 2, "kind": "click", "role": "option", "label": "Paris, Texas"}]}
    assert nav.exact_suggestion("Paris", page) is None


def test_fresh_refuses_a_name_grown_into_a_committing_one():
    from jev_ultrafast.browser import Browser
    b = Browser.__new__(Browser)
    g = [7, "button", "Continuer sans accepter", None, None, None, None, False, None, None, None, None, None, ""]
    page = {"page_key": ["k"], "guards": {"7": g}, "marker": "m"}
    b.evaluate = lambda js: [["k"], [*g[:2], "Continuer sans accepter · 2,99 €", *g[3:]]]
    b.commits = nav.commits
    assert not b.fresh(page, {"kind": "click", "node": 7})
    b.evaluate = lambda js: [["k"], [*g[:2], "Friday 20 , 68 euros", *g[3:]]]
    assert b.fresh({**page, "guards": {"7": [*g[:2], "Friday 20 ????", *g[3:]]}}, {"kind": "click", "node": 7})


def test_done_survives_a_ticking_clock_not_an_error():
    from jev_ultrafast.browser import same_page
    m = [1, "u", 0, 0, 1120, 780, "T", "Panier réservé 09:59", ["a"], []]
    assert same_page([*m[:7], "Panier réservé 09:58", *m[8:]], m)
    assert not same_page([*m[:7], "Panier réservé 09:59 Date invalide", *m[8:]], m)
