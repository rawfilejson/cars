"""make/model base-name extraction — strip trims, keep two-word model names."""

from __future__ import annotations

import pytest

from src.api.makes import _base_model, _canon_token, _order_makes


@pytest.mark.parametrize("tok,expected", [
    ("320i", "320"),     # numeric trim → base number
    ("320d", "320"),
    ("M5", "M5"),        # letter-led → untouched
    ("Camry", "Camry"),
    ("X5", "X5"),
])
def test_canon_token(tok, expected):
    assert _canon_token(tok) == expected


@pytest.mark.parametrize("manufacturer,model,expected", [
    ("Toyota", "Land Cruiser Prado", "Land Cruiser"),  # two-word model kept
    ("BMW", "320i Sedan", "320"),                       # trim number normalized
    ("BMW", "X5 M Sport", "X5"),                         # junk trim dropped
    ("Mazda", "3 Hatchback", "3"),                       # body-type junk not merged
    ("Hyundai", "Hyundai Sonata", "Sonata"),             # manufacturer echo stripped
    ("Mercedes-Benz", "", ""),                           # empty model → empty
])
def test_base_model(manufacturer, model, expected):
    assert _base_model(manufacturer, model) == expected


def test_base_model_drops_manufacturer_case_insensitive():
    assert _base_model("TOYOTA", "toyota Corolla") == "Corolla"


def test_order_makes_by_popularity():
    """მწარმოებლები/მოდელები count-ის კლებადობით; იშვიათები იჭრება."""
    agg = {
        "Toyota": {"camry": ("Camry", 50), "prius": ("Prius", 5), "rare": ("Rare", 2)},
        "BMW": {"320": ("320", 30), "x5": ("X5", 40)},
        "Lada": {"niva": ("Niva", 1)},   # ყველა _MIN_COUNT-ზე ქვემოთ → ქრება
    }
    out = _order_makes(agg)
    # მწარმოებლები ჯამური count-ით: BMW(70) > Toyota(55); Lada საერთოდ არ ჩანს
    assert list(out.keys()) == ["BMW", "Toyota"]
    # მოდელები count-ის კლებადობით; "Rare" (2 < 3) იჭრება
    assert out["BMW"] == ["X5", "320"]
    assert out["Toyota"] == ["Camry", "Prius"]
