"""make/model base-name extraction — strip trims, keep two-word model names."""

from __future__ import annotations

import pytest

from src.api.makes import _base_model, _canon_token


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
