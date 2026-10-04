import pytest

from jev_ultrafast import nav


@pytest.mark.parametrize("label", ["Delete", "Pay now", "Payment", "Book now", "Réserver", "Submit", "Accept all",
                                   "Sign up", "Envoyer", "Eliminar", "Confirm order", "Valider ma commande"])
def test_irreversible_labels_stop(label):
    assert nav.IRREVERSIBLE.search(label)


@pytest.mark.parametrize("label", ["Search", "Done", "Where from?", "Sign in", "Bookmarks", "One way", "Iniciar sesión"])
def test_navigation_labels_pass(label):
    assert not nav.IRREVERSIBLE.search(label)


@pytest.mark.parametrize("key", ["password", "code", "email", "login", "otp", "card_number", "usuario", "pin"])
def test_secret_keys_refused(key):
    assert nav.SECRET.search(key)


@pytest.mark.parametrize("key", ["from", "to", "departure_date", "query", "passengers", "postal", "review"])
def test_plain_keys_allowed(key):
    assert not nav.SECRET.search(key)


def test_missing_values_stop_before_any_model_call():
    with pytest.raises(nav.Stop) as stop:
        nav.value_chooser({}, [])({"goal": "g", "field": {"label": "City"}, "page": {}, "recent_actions": []})
    assert stop.value.status == "need_value" and stop.value.info == {"field": "City"}
