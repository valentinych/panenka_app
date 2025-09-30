from app.routes import PlayerNameNormalizer


def _build_normalizer(names: list[str]) -> PlayerNameNormalizer:
    normalizer = PlayerNameNormalizer()
    normalizer.build(names)
    return normalizer


def test_placeholder_values_are_skipped():
    normalizer = PlayerNameNormalizer()
    assert normalizer.canonicalize("Пусто") is None
    assert normalizer.canonicalize("--") is None
    assert normalizer.canonicalize("---") is None
    assert normalizer.canonicalize(".") is None


def test_reversed_first_last_names_merge():
    names = ["Руслан Огородник", "Огородник Руслан"]
    normalizer = _build_normalizer(names)

    assert normalizer.canonicalize("Огородник Руслан") == "Руслан Огородник"
    assert normalizer.canonicalize("Руслан Огородник") == "Руслан Огородник"


def test_initials_expand_to_full_name():
    names = [
        "Мария Т.",
        "Мария Тимохова",
        "Станислав С-Б.",
        "Станислав Силицкий-Бутрим",
        "Максим Корнеевец",
        "Максим К.",
    ]
    normalizer = _build_normalizer(names)

    assert normalizer.canonicalize("Мария Т.") == "Мария Тимохова"
    assert normalizer.canonicalize("Станислав С-Б.") == "Станислав Силицкий-Бутрим"
    assert normalizer.canonicalize("Максим К.") == "Максим Корнеевец"


def test_manual_override_disambiguates_initial():
    names = [
        "Александр Комса",
        "Александр Квасневский",
        "Александр К.",
    ]
    normalizer = _build_normalizer(names)

    assert normalizer.canonicalize("Александр К.") == "Александр Комса"


def test_unique_single_token_maps_to_full_name():
    names = [
        "Арсений Соломин",
        "Арсений",
        "Соломин",
    ]
    normalizer = _build_normalizer(names)

    assert normalizer.canonicalize("Арсений") == "Арсений Соломин"
    assert normalizer.canonicalize("Соломин") == "Арсений Соломин"


def test_unique_given_name_maps_to_canonical():
    names = ["Хорхе Чаос", "Хорхе"]
    normalizer = _build_normalizer(names)

    assert normalizer.canonicalize("Хорхе") == "Хорхе Чаос"
