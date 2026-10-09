import pytest

from jev_ultrafast import nav


@pytest.mark.parametrize("label", ["Delete", "Pay now", "Payment", "Book now", "Réserver", "Submit", "Accept all",
                                   "Sign up", "Envoyer", "Eliminar", "Confirm order", "Valider ma commande",
                                   "Supprimer le projet", "Cancel subscription", "Annuler mon abonnement", "Résilier",
                                   "Payer", "Déclarer", "Autoriser l'accès", "Publier", "Se déconnecter", "Log out",
                                   "Reserve now", "Payez", "Passer commande", "Complete booking", "Finalizar compra",
                                   "Partager", "Share", "Invite", "Create account", "Créer un compte", "Register",
                                   "Envoyez", "Supprimez"])
def test_irreversible_labels_stop(label):
    assert nav.IRREVERSIBLE.search(label)


@pytest.mark.parametrize("label", ["Search", "Done", "Where from?", "Sign in", "Bookmarks", "One way", "Iniciar sesión",
                                   "Pays", "Paysage", "Enregistrer", "Save", "Mettre à jour", "Modifier", "Archiver",
                                   "Annuler", "Cancel", "Ajouter", "Renommer", "Mes commandes", "Réservations"])
def test_navigation_labels_pass(label):
    assert not nav.IRREVERSIBLE.search(label)


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
