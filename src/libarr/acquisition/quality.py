"""Quality profiles (plan 2.3.1): format taxonomy, custom formats, cutoff."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Text profile: EPUB > AZW3 > MOBI > PDF > FB2 > other.
_TEXT_FORMAT_SCORES = {
    "EPUB": 100,
    "AZW3": 90,
    "MOBI": 80,
    "PDF": 60,
    "FB2": 50,
    "OTHER": 10,
}

# Audiobook profile: M4B > MP3 > other.
_AUDIO_FORMAT_SCORES = {
    "M4B": 100,
    "MP3": 80,
    "OTHER": 10,
}

# Custom format matchers: +positive / -negative, applied to title+description.
_CUSTOM_MATCHERS: list[tuple[str, int, re.Pattern[str]]] = [
    ("retail", +10, re.compile(r"\bretail\b|\btrue\s+epub\b", re.IGNORECASE)),
    ("drm-free", +10, re.compile(r"\bdrm[-\s]?free\b|\bproper\b", re.IGNORECASE)),
    ("sample", -20, re.compile(r"\[sample[^\]]*\]|\bsample\b", re.IGNORECASE)),
    ("unknown", -20, re.compile(r"\[unknown\]|\bunknown\b", re.IGNORECASE)),
]


@dataclass(slots=True)
class QualityProfile:
    name: str = "Standard"
    allowed_formats: tuple[str, ...] = ("EPUB", "AZW3", "MOBI", "PDF")
    cutoff_format: str | None = "EPUB"
    custom_formats: tuple[str, ...] = ("+Retail", "+DRM-Free", "-Sample", "-Unknown")
    language: str | None = None
    kind: str = "text"  # text | audio — selects the format taxonomy

    def __post_init__(self) -> None:
        if self.kind not in ("text", "audio"):
            raise ValueError(f"invalid profile kind: {self.kind}")


def _taxonomy(profile: QualityProfile) -> dict[str, int]:
    return _TEXT_FORMAT_SCORES if profile.kind == "text" else _AUDIO_FORMAT_SCORES


def format_score(profile: QualityProfile, fmt: str | None) -> int:
    """Score for a format under this profile. 0 = not allowed."""
    if fmt is None:
        return 0
    taxonomy = _taxonomy(profile)
    score = taxonomy.get(fmt.upper())
    if score is None:
        score = taxonomy.get("OTHER", 0)
    allowed = {f.upper() for f in profile.allowed_formats}
    return score if fmt.upper() in allowed else 0


def custom_format_score(profile: QualityProfile, title: str, description: str = "") -> int:
    """Sum of enabled custom-format matchers over the release text."""
    haystack = f"{title} {description}"
    total = 0
    for name, weight, pattern in _CUSTOM_MATCHERS:
        enabled = any(name in cf.lower() for cf in profile.custom_formats)
        if enabled and pattern.search(haystack):
            total += weight
    return total


def meets_cutoff(fmt: str | None, profile: QualityProfile) -> bool:
    """True when an existing file at this format satisfies the profile cutoff."""
    if fmt is None or profile.cutoff_format is None:
        return False
    return format_score(profile, fmt) >= format_score(profile, profile.cutoff_format)


def is_upgrade(
    *,
    current_format: str | None,
    candidate_format: str | None,
    profile: QualityProfile,
) -> bool:
    """Sonarr-style upgrade eligibility: candidate beats current, and the
    current file is below the profile cutoff."""
    if current_format is None:
        return candidate_format is not None and format_score(profile, candidate_format) > 0
    if meets_cutoff(current_format, profile):
        return False
    if candidate_format is None:
        return False
    return format_score(profile, candidate_format) > format_score(profile, current_format)
