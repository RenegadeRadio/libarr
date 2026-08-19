"""Normalization utilities: text folding, slugs, ISBN validation/conversion."""

from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    """Fold text for matching: NFKD, drop combining marks, lowercase, strip punctuation."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    # Ligatures that NFKD does not decompose ("Æsop" must match "Aesop").
    text = text.translate(_LIGATURES)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_LIGATURES = str.maketrans(
    {
        "æ": "ae",
        "œ": "oe",
        "ß": "ss",
        "ø": "oe",
        "ð": "d",
        "þ": "th",
        "đ": "d",
        "ł": "l",
        "ı": "i",
    }
)


def slugify(text: str) -> str:
    """ASCII slug for facets and URLs."""
    slug = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
    return slug or "untitled"


def normalize_isbn(raw: str | None) -> str | None:
    """Validate and normalize an ISBN to ISBN-13 (converting ISBN-10). None if invalid."""
    if not raw:
        return None
    digits = re.sub(r"[^0-9Xx]", "", raw).upper()
    if len(digits) == 13:
        return digits if _isbn13_valid(digits) else None
    if len(digits) == 10:
        return _isbn10_to_13(digits) if _isbn10_valid(digits) else None
    return None


def _isbn13_valid(digits: str) -> bool:
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(digits[:12]))
    check = (10 - total % 10) % 10
    return check == int(digits[12])


def _isbn10_valid(digits: str) -> bool:
    total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits))
    return total % 11 == 0


def _isbn10_to_13(digits: str) -> str:
    base = "978" + digits[:9]
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(base))
    return base + str((10 - total % 10) % 10)
