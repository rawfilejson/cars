# make/model base-name extraction - strip trims, keep two-word model names.

from __future__ import annotations

import pytest

from src.api.makes import _base_model, _canon_token, _order_makes


@pytest.mark.parametrize(
    "tok,expected",
    [
        ("320i", "320"),  # numeric trim -> base number
        ("320d", "320"),
        ("M5", "M5"),  # letter-led -> untouched
        ("Camry", "Camry"),
        ("X5", "X5"),
    ],
)
def test_canon_token(tok, expected):
    assert _canon_token(tok) == expected


@pytest.mark.parametrize(
    "manufacturer,model,expected",
    [
        ("Toyota", "Land Cruiser Prado", "Land Cruiser"),  # two-word model kept
        ("BMW", "320i Sedan", "320"),  # trim number normalized
        ("BMW", "X5 M Sport", "X5"),  # junk trim dropped
        ("Mazda", "3 Hatchback", "3"),  # body-type junk not merged
        ("Hyundai", "Hyundai Sonata", "Sonata"),  # manufacturer echo stripped
        ("Mercedes-Benz", "", ""),  # empty model -> empty
        # letter-series + number -> the number is the submodel, kept
        ("Mercedes-Benz", "C 300 4MATIC Sedan", "C 300"),
        ("Mercedes-Benz", "GLE 350 de", "GLE 350"),
        ("Mercedes-Benz", "E 220d", "E 220"),  # trim suffix canonicalized
        ("Mercedes-Benz", "S 500 L", "S 500"),
        ("Mercedes-Benz", "C 4MATIC", "C"),  # no series number -> base class
        # word models keep dropping trailing numbers/trims
        ("Toyota", "Camry 70", "Camry"),
        ("Audi", "RS 6", "RS"),  # single digit - not a series number
    ],
)
def test_base_model(manufacturer, model, expected):
    assert _base_model(manufacturer, model) == expected


def test_base_model_drops_manufacturer_case_insensitive():
    assert _base_model("TOYOTA", "toyota Corolla") == "Corolla"


def test_rare_submodel_folds_into_base_class():
    # C 43 (2 of them) is not lost, it folds into the "C" class entry
    from unittest.mock import MagicMock, patch

    from src.api import makes as makes_mod

    rows = [
        {"manufacturer": "Mercedes-Benz", "model": "C 300", "c": 5},
        {"manufacturer": "Mercedes-Benz", "model": "C 43 AMG", "c": 2},
        {"manufacturer": "Mercedes-Benz", "model": "C 4MATIC", "c": 2},
    ]
    cur = MagicMock()
    cur.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    with patch.object(makes_mod, "connection", return_value=ctx):
        out = makes_mod._load_makes().makes
    # C 300 stays on its own
    # rare C 43 and C 4MATIC merge into "C" (2+2=4 >= 3)
    assert out["Mercedes-Benz"] == ["C 300", "C"]


def test_order_makes_by_popularity():
    # manufacturers and models by descending count, with rare models dropped
    agg = {
        "Toyota": {"camry": ("Camry", 50), "prius": ("Prius", 5), "rare": ("Rare", 2)},
        "BMW": {"320": ("320", 30), "x5": ("X5", 40)},
    }
    out = _order_makes(agg)
    # manufacturers by total count: BMW(70) > Toyota(55)
    assert list(out.keys()) == ["BMW", "Toyota"]
    # models by descending count. "Rare" (2 < 3) is dropped
    assert out["BMW"] == ["X5", "320"]
    assert out["Toyota"] == ["Camry", "Prius"]


def test_small_brand_with_single_listing_still_appears():
    # even a lone Bugatti has to reach the dropdown
    # a brand is never lost
    agg = {
        "Toyota": {"camry": ("Camry", 50)},
        "Bugatti": {"chiron": ("Chiron", 1)},
    }
    out = _order_makes(agg)
    assert out["Bugatti"] == ["Chiron"]
