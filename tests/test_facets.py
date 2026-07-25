# facets canonicalization — dirty variant → one canonical value, and back.

from __future__ import annotations

import pytest

from src.api.facets import facet_canon, facet_variants


@pytest.mark.parametrize("raw,canon", [
    ("ჰეჩბეკი", "ჰეტჩბეკი"),
    ("ჰეტჩბექი", "ჰეტჩბეკი"),
    ("ჰეჩბექი", "ჰეტჩბეკი"),
    ("ბენზინზე", "ბენზინი"),
    ("დიზელზე", "დიზელი"),
    ("4X4", "4x4"),
    ("სედანი", "სედანი"),   # unknown → unchanged
    ("", ""),
])
def test_facet_canon(raw, canon):
    assert facet_canon(raw) == canon


def test_facet_variants_includes_canonical_first():
    variants = facet_variants("ჰეტჩბეკი")
    assert variants[0] == "ჰეტჩბეკი"
    # every dirty spelling that canonicalizes to it must be a filter variant
    assert set(variants) == {"ჰეტჩბეკი", "ჰეჩბეკი", "ჰეტჩბექი", "ჰეჩბექი"}


def test_facet_variants_4x4():
    assert set(facet_variants("4x4")) == {"4x4", "4X4"}


def test_facet_variants_no_aliases_is_singleton():
    assert facet_variants("სედანი") == ["სედანი"]


def test_facet_variants_have_no_duplicates():
    for value in ("ჰეტჩბეკი", "ბენზინი", "4x4", "სედანი"):
        variants = facet_variants(value)
        assert len(variants) == len(set(variants))
