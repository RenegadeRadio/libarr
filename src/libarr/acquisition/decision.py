"""The decision engine (plan 2.3.2): pick the best release.

Comparer order, Sonarr-style but book-flavored:
    1. Format score (profile)        — EPUB beats PDF, always
    2. Custom-format score           — +Retail/+DRM-Free, -Sample/-Unknown
    3. Protocol                      — direct > usenet > torrent (legal-first)
    4. Indexer priority              — lower number = higher priority
    5. Seeds/Peers                   — healthier torrent wins
    6. Age                           — newer preferred
    7. Size                          — smaller preferred (leaner text file)
"""

from __future__ import annotations

from libarr.acquisition.candidates import Candidate
from libarr.acquisition.quality import QualityProfile, custom_format_score, format_score

_PROTOCOL_RANK = {"direct": 3, "usenet": 2, "torrent": 1}


def _score(candidate: Candidate, profile: QualityProfile) -> tuple[object, ...]:
    """Comparable tuple for one candidate under a profile."""
    return (
        format_score(profile, candidate.fmt),
        candidate.custom_score,
        _PROTOCOL_RANK.get(candidate.protocol, 0),
        -candidate.indexer_priority,  # lower priority number wins
        candidate.seeders or 0,
        -(candidate.age_hours or 0.0),  # newer (smaller age) wins
        -(candidate.size_bytes or 0),  # smaller wins for text
    )


def pick_best(
    candidates: list[Candidate],
    profile: QualityProfile,
) -> Candidate | None:
    """The best candidate under the profile, or None if nothing is eligible.

    Candidates with a disallowed format score 0 on the format axis; if every
    candidate scores 0 there, nothing is picked (Sonarr semantics).
    """
    eligible = [c for c in candidates if format_score(profile, c.fmt) > 0]
    if not eligible:
        return None
    # Fill custom scores per profile before ranking.
    for candidate in eligible:
        if candidate.custom_score == 0:
            candidate.custom_score = custom_format_score(profile, candidate.release.title)
    return max(eligible, key=lambda c: _score(c, profile))
