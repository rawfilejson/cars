"""Cleanup helpers for messy data from car listing sites.

Raw text from these sites looks like "$11 500", "312 000 კმ. / 195 000 მილი",
"2.5 ლ". We turn that into numbers we can sort and search by.
"""

from __future__ import annotations

import re


_PRICE_USD = re.compile(r"\$|usd", re.IGNORECASE)
_PRICE_EUR = re.compile(r"€|eur", re.IGNORECASE)
_PRICE_GEL = re.compile(r"₾|gel|ლარ", re.IGNORECASE)


def clean_int(text: str | None) -> int | None:
    """Strip everything non-digit, return int. Empty in → None."""
    if not text:
        return None
    digits = re.sub(r"\D", "", str(text))
    return int(digits) if digits else None


def clean_decimal(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", str(text))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def split_price(raw: str | None) -> tuple[int | None, str]:
    """`$9 500` → (9500, "USD"). Detects $, €, ₾, or GEL/USD/EUR words."""
    if not raw:
        return None, ""

    amount = clean_int(raw)
    if amount is None:
        return None, ""

    if _PRICE_USD.search(raw):
        return amount, "USD"
    if _PRICE_EUR.search(raw):
        return amount, "EUR"
    if _PRICE_GEL.search(raw):
        return amount, "GEL"

    return amount, ""


def format_phone(raw: str | None) -> str:
    """Normalize to E.164-ish format. Always returns "+" prefix or empty.

    Handles:
      "tel:+995595..."  → "+995595..."
      9-digit GE mobile → prepend +995
      Russian 11-digit  → just prepend +
      Anything else     → strip non-digits and prepend +
    """
    if not raw:
        return ""

    digits = re.sub(r"\D", "", str(raw).replace("tel:", ""))
    if not digits:
        return ""

    if digits.startswith("995") and len(digits) >= 11:
        return "+" + digits
    if len(digits) == 9 and digits[0] in ("5", "7", "3"):
        return "+995" + digits
    if len(digits) == 11 and digits[0] == "7":
        return "+" + digits
    return "+" + digits


def normalize_steering(text: str | None) -> str:
    if not text:
        return ""
    if "მარცხენა" in text:
        return "მარცხენა"
    if "მარჯვენა" in text:
        return "მარჯვენა"
    return ""


def parse_customs(text: str | None) -> bool | None:
    """Returns True if cleared, False if not, None if unknown."""
    if not text:
        return None
    text = text.strip()
    if "განუბაჟ" in text:
        return False
    if "განბაჟ" in text:
        return True
    return None


def parse_bool_yes_no(text: str | None) -> bool | None:
    if not text:
        return None
    text = text.strip().lower()
    if text in ("კი", "დიახ", "yes", "true", "1"):
        return True
    if text in ("არა", "no", "false", "0"):
        return False
    return None


def clean_text(text: str | None) -> str:
    """Collapse extra whitespace, leave structure intact."""
    if not text:
        return ""
    cleaned = re.sub(r"\n{3,}", "\n\n", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def clean_engine_volume(text: str | None) -> float | None:
    """Engine volume in liters. Handles common bad-data cases:

      "2.5 ლ"    → 2.5
      "1499"     → 1.499 (was entered in CC instead of L)
      "460"      → None (impossible, treat as garbage)
    """
    value = clean_decimal(text)
    if value is None:
        return None

    if 0.1 <= value <= 50:
        return value
    if 50 < value <= 30000:
        # Looks like cubic centimeters — convert to liters.
        return round(value / 1000, 2)
    return None
