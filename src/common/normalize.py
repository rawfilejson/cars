"""
ტექსტური მონაცემების გასუფთავება და ნორმალიზაცია.

საიტიდან მონაცემები ჩვეულებრივ მოდის "ბინძურად":
  * ფასი — "$11 500" (ნიშანი + არასაჭირო space-ები)
  * გარბენი — "312 000 კმ. / 195 000 მილი" (ორი ერთეული, ერთად)
  * ნომერი — "tel:+995595..." ან "595..."
  * წელი — "2021 წ." (text-ი ციფრების გვერდით)

ეს მოდული ამ ბინძურ ფორმებს გადააქცევს ნორმალურ ფორმაში: int-ად, float-ად,
+-ით დაწყებულ ნომრად და ა.შ. PostgreSQL-ში ნორმალურად ჩასაწერად.
"""

from __future__ import annotations

import re


# ფასის ნიშნები
_PRICE_USD_RE = re.compile(r"\$|usd", re.IGNORECASE)
_PRICE_EUR_RE = re.compile(r"€|eur", re.IGNORECASE)
_PRICE_GEL_RE = re.compile(r"₾|gel|ლარ", re.IGNORECASE)


def clean_int(text: str | None) -> int | None:
    """ციფრების ამოღება და int-ად დაბრუნება.

    "$11 500" → 11500
    "2021 წ." → 2021
    ცარიელი/არ-ციფრიანი → None
    """
    if not text:
        return None
    digits = re.sub(r"\D", "", str(text))
    return int(digits) if digits else None


def clean_decimal(text: str | None) -> float | None:
    """წილადი რიცხვის ამოღება.

    "2.5 ლ" → 2.5
    "1,6" → 1.6 (ქართულ ლოკაიზაციაში მძიმე)
    """
    if not text:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", str(text))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def clean_engine_volume(text: str | None) -> float | None:
    """ძრავის მოცულობა ლიტრებში — smart cleanup.

    რეალური დიაპაზონი: 0.5 — 12.0 ლიტრი (პასაჟირული) ან 20+ (კომერციული).
    წყაროში ცუდი მონაცემები გვხვდება:
      * "1499" — CC-ში (cubic centimeters) იყო ჩაწერილი → 1.499 L
      * "460" — typo (460L ფიზიკურად შეუძლებელია, ალბათ 4.6)
      * "999" — placeholder ცარიელი მნიშვნელობისთვის

    წესები:
      * 0.1 — 50.0 → უცვლელად
      * 50 — 30000 (CC) → /1000-ზე (1500 cc → 1.5 L)
      * > 30000 → None (აშკარა garbage)
    """
    value = clean_decimal(text)
    if value is None:
        return None

    if 0.1 <= value <= 50:
        return value
    if 50 < value <= 30000:                          # CC-ში ჩაწერილი
        return round(value / 1000, 2)
    return None                                      # garbage


def split_price(raw: str | None) -> tuple[int | None, str]:
    """ფასი + ვალუტა ცალკე-ცალკე.

    "$9 500"   → (9500,  "USD")
    "€12 000"  → (12000, "EUR")
    "1500 ₾"   → (1500,  "GEL")
    """
    if not raw:
        return None, ""

    amount = clean_int(raw)
    if amount is None:
        return None, ""

    if _PRICE_USD_RE.search(raw):
        return amount, "USD"
    if _PRICE_EUR_RE.search(raw):
        return amount, "EUR"
    if _PRICE_GEL_RE.search(raw):
        return amount, "GEL"

    return amount, ""


def format_phone(raw: str | None) -> str:
    """ნომრის ნორმალიზაცია — ყოველთვის +-ით და სრული საერთაშორისო კოდით.

    წესები:
      * "tel:+995595..."  → "+995595..."
      * 9 ნიშნა საქართველო (5/7/3-ით იწყება) → +995 ემატება
      * 11 ნიშნა რუსეთი (7-ით) → მარტო + ემატება
      * სხვა შემთხვევაში — უბრალოდ + ემატება წინ
    """
    if not raw:
        return ""

    # მხოლოდ ციფრების დატოვება
    digits = re.sub(r"\D", "", str(raw).replace("tel:", ""))
    if not digits:
        return ""

    # უკვე ქართული ნომერი (995-ით იწყება)
    if digits.startswith("995") and len(digits) >= 11:
        return "+" + digits

    # ქართული მობილური 9 ციფრიანი
    if len(digits) == 9 and digits[0] in ("5", "7", "3"):
        return "+995" + digits

    # რუსეთის 11 ციფრიანი (7-ით იწყება)
    if len(digits) == 11 and digits[0] == "7":
        return "+" + digits

    # უცნობი ფორმატი — უბრალოდ + წინ
    return "+" + digits


def normalize_steering(text: str | None) -> str:
    """საჭე — მარცხენა/მარჯვენა."""
    if not text:
        return ""
    if "მარცხენა" in text:
        return "მარცხენა"
    if "მარჯვენა" in text:
        return "მარჯვენა"
    return ""


def parse_customs(text: str | None) -> bool | None:
    """განბაჟებული → True, განუბაჟებელი → False, უცნობი → None."""
    if not text:
        return None
    text = text.strip()
    if "განუბაჟ" in text:
        return False
    if "განბაჟ" in text:
        return True
    return None


def parse_bool_yes_no(text: str | None) -> bool | None:
    """„კი"/„დიახ" → True, „არა" → False, სხვა → None."""
    if not text:
        return None
    text = text.strip().lower()
    if text in ("კი", "დიახ", "yes", "true", "1"):
        return True
    if text in ("არა", "no", "false", "0"):
        return False
    return None


def clean_text(text: str | None) -> str:
    """ზედმეტი whitespace-ის გასუფთავება, multi-newline → double-newline."""
    if not text:
        return ""
    # მრავალი ცარიელი ხაზი → ორი
    cleaned = re.sub(r"\n{3,}", "\n\n", text)
    # მრავალი space → ერთი (მაგრამ newline-ი არ შევცვალოთ)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()
