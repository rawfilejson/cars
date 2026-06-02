"""Sanity checks on a scraped Car before we trust it.

These don't block the insert — they just return a list of issues we can log.
The point is visibility: if 30% of cars come back with `year 1850`, we know
the parser's broken before we ship.
"""

from __future__ import annotations

from .models import Car


YEAR_MIN, YEAR_MAX = 1900, 2030
PRICE_MAX = 10_000_000
MILEAGE_MAX = 2_000_000
ENGINE_L_MIN, ENGINE_L_MAX = 0.1, 10.0
HP_MAX = 2_000
CYLINDERS_MAX = 16
DOORS_MAX = 8
SEATS_MAX = 50

VALID_CURRENCIES = {"USD", "EUR", "GEL", ""}


def validate_car(car: Car) -> list[str]:
    """Return a list of issue strings. Empty list = clean."""
    issues: list[str] = []

    if not car.source:
        issues.append("missing source")
    if not car.source_id:
        issues.append("missing source_id")
    if not car.url:
        issues.append("missing url")

    if car.year is not None and not (YEAR_MIN <= car.year <= YEAR_MAX):
        issues.append(f"year {car.year} out of range {YEAR_MIN}-{YEAR_MAX}")

    if car.price_amount is not None:
        if car.price_amount <= 0:
            issues.append(f"price_amount {car.price_amount} not positive")
        elif car.price_amount > PRICE_MAX:
            issues.append(f"price_amount {car.price_amount} too high")

    if car.price_currency not in VALID_CURRENCIES:
        issues.append(f"price_currency {car.price_currency!r} not in {VALID_CURRENCIES}")

    if car.mileage_km is not None and not (0 <= car.mileage_km <= MILEAGE_MAX):
        issues.append(f"mileage_km {car.mileage_km} out of range 0-{MILEAGE_MAX}")

    if car.engine_volume_l is not None:
        if not (ENGINE_L_MIN <= car.engine_volume_l <= ENGINE_L_MAX):
            issues.append(
                f"engine_volume_l {car.engine_volume_l} out of range "
                f"{ENGINE_L_MIN}-{ENGINE_L_MAX}"
            )

    if car.power_hp is not None and not (1 <= car.power_hp <= HP_MAX):
        issues.append(f"power_hp {car.power_hp} out of range 1-{HP_MAX}")

    if car.cylinders is not None and not (1 <= car.cylinders <= CYLINDERS_MAX):
        issues.append(f"cylinders {car.cylinders} out of range 1-{CYLINDERS_MAX}")

    if car.doors is not None and not (1 <= car.doors <= DOORS_MAX):
        issues.append(f"doors {car.doors} out of range 1-{DOORS_MAX}")

    if car.seats is not None and not (1 <= car.seats <= SEATS_MAX):
        issues.append(f"seats {car.seats} out of range 1-{SEATS_MAX}")

    if car.vin and len(car.vin) != 17:
        issues.append(f"vin {car.vin!r} length {len(car.vin)} (must be 17 or empty)")

    if car.phone and not car.phone.startswith("+"):
        issues.append(f"phone {car.phone!r} must start with +")

    return issues
