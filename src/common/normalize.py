# Cleanup helpers for messy data from car listing sites.
#
# Raw text from these sites looks like "$11 500", "312 000 კმ. / 195 000 მილი",
# "2.5 ლ". We turn that into numbers we can sort and search by.

from __future__ import annotations

import re


_PRICE_USD = re.compile(r"\$|usd", re.IGNORECASE)
_PRICE_EUR = re.compile(r"€|eur", re.IGNORECASE)
_PRICE_GEL = re.compile(r"₾|gel|ლარ", re.IGNORECASE)


def clean_int(text: str | None) -> int | None:
    # Strip everything non-digit, return int. Empty in → None.
    if not text:
        return None
    digits = re.sub(r"\D", "", str(text))
    return int(digits) if digits else None


def sane_int(text: str | None, lo: int, hi: int) -> int | None:
    # clean_int + range check. Out-of-range → None.
    #
    # Use for fields where sellers commonly enter garbage (e.g. HP "2490"
    # when they meant engine cc). Better to drop than to lie.
    value = clean_int(text)
    if value is None or value < lo or value > hi:
        return None
    return value


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
    # `$9 500` → (9500, "USD"). Detects $, €, ₾, or GEL/USD/EUR words.
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
    # Georgian numbers are displayed as "+995 595 515 141".
    #
    # Search ignores the spaces: regexp_replace(phone, '\\D', '', 'g') reduces it to
    # digits and then LIKE matches on those. So we store it prettily and search on
    # the digits.
    #
    # Examples:
    #   "tel:+995595515141" → "+995 595 515 141"
    #   "595 51 51 41"      → "+995 595 515 141"
    #   "+995595515141"     → "+995 595 515 141"
    #   "+7 916 123 45 67"  → "+7 916 123 45 67"
    #   ""                  → ""
    if not raw:
        return ""

    digits = re.sub(r"\D", "", str(raw).replace("tel:", ""))
    if not digits:
        return ""

    if digits.startswith("995") and len(digits) == 12:
        return _format_ge(digits[3:])
    if len(digits) == 9 and digits[0] in ("5", "7", "3"):
        return _format_ge(digits)

    if len(digits) == 11 and digits[0] == "7":
        return f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:]}"

    return "+" + digits


def _format_ge(nine_digits: str) -> str:
    # a 9-digit Georgian mobile becomes "+995 595 515 141" (3-3-3)
    return f"+995 {nine_digits[:3]} {nine_digits[3:6]} {nine_digits[6:]}"


_PHONE_IN_TEXT_RE = re.compile(r"(?:\+?\s?995[\s\-.]?)?5\d{2}(?:[\s\-.]?\d){6}")


def phone_from_text(text: str | None) -> str:
    # pull a Georgian mobile (5XX XXX XXX) out of free text, for when the seller
    # typed it into the description instead of the phone field. Returns "" if absent.
    if not text:
        return ""
    match = _PHONE_IN_TEXT_RE.search(str(text))
    if not match:
        return ""
    digits = re.sub(r"\D", "", match.group(0))
    if digits.startswith("995"):
        digits = digits[3:]
    if len(digits) != 9 or digits[0] != "5":
        return ""
    return _format_ge(digits)


def normalize_steering(text: str | None) -> str:
    if not text:
        return ""
    if "მარცხენა" in text:
        return "მარცხენა"
    if "მარჯვენა" in text:
        return "მარჯვენა"
    return ""


def parse_customs(text: str | None) -> bool | None:
    # Returns True if cleared, False if not, None if unknown.
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
    # Collapse extra whitespace, leave structure intact.
    if not text:
        return ""
    cleaned = re.sub(r"\n{3,}", "\n\n", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def clean_engine_volume(text: str | None) -> float | None:
    # Engine volume in liters. Handles common bad-data cases:
    #
    # "2.5 ლ"    → 2.5
    # "1499"     → 1.499 (was entered in CC instead of L)
    # "460"      → None (impossible, treat as garbage)
    value = clean_decimal(text)
    if value is None:
        return None

    if 0.1 <= value <= 50:
        return value
    if 50 < value <= 30000:
        return round(value / 1000, 2)
    return None
