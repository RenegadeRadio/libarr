"""Phase 2.3 — quality profiles: format taxonomy, custom formats, cutoff."""

import pytest

from libarr.acquisition.quality import (
    QualityProfile,
    custom_format_score,
    format_score,
    is_upgrade,
    meets_cutoff,
)


def _profile(**kw):
    defaults = dict(
        name="Standard",
        allowed_formats=("EPUB", "AZW3", "MOBI", "PDF"),
        cutoff_format="EPUB",
        custom_formats=("+Retail", "+DRM-Free", "-Sample", "-Unknown"),
        language=None,
        kind="text",
    )
    defaults.update(kw)
    return QualityProfile(**defaults)


def test_format_scores_follow_taxonomy():
    p = _profile()
    assert format_score(p, "EPUB") == 100
    assert format_score(p, "AZW3") == 90
    assert format_score(p, "MOBI") == 80
    assert format_score(p, "PDF") == 60
    # Disallowed / unknown formats score zero.
    assert format_score(p, "M4B") == 0
    assert format_score(p, None) == 0


def test_audio_profile_taxonomy():
    p = _profile(kind="audio", allowed_formats=("M4B", "MP3"), cutoff_format="M4B")
    assert format_score(p, "M4B") == 100
    assert format_score(p, "MP3") == 80
    assert format_score(p, "EPUB") == 0


def test_custom_format_scoring():
    assert custom_format_score(_profile(), "Dune (2021) EPUB retail") == 10
    assert custom_format_score(_profile(), "Dune DRM-Free EPUB") == 10
    assert custom_format_score(_profile(), "Dune proper EPUB") == 10  # proper ≈ DRM-free
    assert custom_format_score(_profile(), "Dune EPUB") == 0
    # Negative custom formats subtract.
    assert custom_format_score(_profile(), "Dune EPUB [sample]") == -20
    assert custom_format_score(_profile(), "Dune EPUB unknown") == -20


def test_meets_cutoff():
    p = _profile()
    assert meets_cutoff("EPUB", p) is True
    assert meets_cutoff("AZW3", p) is False
    assert meets_cutoff("MOBI", p) is False


def test_is_upgrade_semantics():
    p = _profile()
    # EPUB (cutoff) beats MOBI: candidate is a genuine upgrade.
    assert is_upgrade(current_format="MOBI", candidate_format="EPUB", profile=p) is True
    # Current already meets cutoff → nothing is an upgrade.
    assert is_upgrade(current_format="EPUB", candidate_format="AZW3", profile=p) is False
    # Same format is never an upgrade.
    assert is_upgrade(current_format="EPUB", candidate_format="EPUB", profile=p) is False
    # Downgrades are not upgrades.
    assert is_upgrade(current_format="MOBI", candidate_format="PDF", profile=p) is False
    # No current file → any allowed candidate is an upgrade.
    assert is_upgrade(current_format=None, candidate_format="PDF", profile=p) is True


def test_profile_rejects_invalid_kind():
    with pytest.raises(ValueError):
        _profile(kind="video")
