# VIN extraction and validation.
# A VIN is exactly 17 characters: digits and uppercase letters,
# excluding I, O and Q (so they don't get confused with 1 and 0).
# We don't verify the checksum - real-world listings often have invalid
# checksums and we'd rather show them than drop them.

from __future__ import annotations

import re


VIN_PATTERN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def is_valid_vin(text: str) -> bool:
    if not text or len(text) != 17 or "*" in text:
        return False
    return bool(VIN_PATTERN.fullmatch(text.upper()))


def find_vin(text: str) -> str:
    # Return the first VIN found in `text`, uppercased.
    # Masked VINs like "KMHL34*****" are skipped - we wipe out any token
    # containing `*` before searching.
    if not text:
        return ""

    upper = text.upper()
    cleaned = re.sub(r"[A-Z0-9]*\*+[A-Z0-9*]*", " ", upper)

    match = VIN_PATTERN.search(cleaned)
    if not match:
        return ""

    candidate = match.group(0)
    return candidate if is_valid_vin(candidate) else ""


def best_vin(*sources: str) -> str:
    # Try each source in order, return first valid VIN found.
    for src in sources:
        vin = find_vin(src) if src else ""
        if vin:
            return vin
    return ""
