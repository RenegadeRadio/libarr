"""Phase 2.3 — the decision engine comparer + candidate normalization."""

import json
from pathlib import Path
from typing import Any

import pytest

from libarr.acquisition.candidates import Candidate, is_junk, normalize_candidate
from libarr.acquisition.decision import pick_best
from libarr.acquisition.quality import QualityProfile
from libarr.indexers.base import Release


def _profile(**kw: Any) -> QualityProfile:
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


def _release(**kw: Any) -> Release:
    defaults = dict(
        title="Dune - Frank Herbert (1965) EPUB",
        indexer_name="idx",
        download_url="http://x/d/1.torrent",
        guid="g1",
        format="EPUB",
        size_bytes=1000,
        seeders=10,
        published_at=None,
    )
    defaults.update(kw)
    return Release(**defaults)


def _candidate(**kw: Any) -> Candidate:
    defaults = dict(
        release=_release(),
        fmt="EPUB",
        custom_score=0,
        protocol="torrent",
        indexer_priority=100,
        seeders=10,
        age_hours=100.0,
        size_bytes=1000,
    )
    defaults.update(kw)
    release = defaults.pop("release")
    return Candidate(release=release, parsed=None, **defaults)


def test_format_beats_everything_else():
    c = [
        _candidate(fmt="PDF", size_bytes=100),
        _candidate(fmt="EPUB", size_bytes=9000, seeders=0),
    ]
    assert pick_best([c[0], c[1]], _profile()).fmt == "EPUB"


def test_custom_format_beats_plain_same_format():
    c = [
        _candidate(custom_score=0),
        _candidate(custom_score=10, seeders=0),
    ]
    assert pick_best(list(reversed(c)), _profile()).custom_score == 10


def test_protocol_order_direct_over_torrent():
    c = [
        _candidate(protocol="torrent"),
        _candidate(protocol="direct", seeders=0),
    ]
    assert pick_best(list(reversed(c)), _profile()).protocol == "direct"


def test_indexer_priority_tiebreak():
    c = [
        _candidate(indexer_priority=100),
        _candidate(indexer_priority=1, seeders=0),
    ]
    assert pick_best(list(reversed(c)), _profile()).indexer_priority == 1


def test_seeders_tiebreak():
    c = [
        _candidate(seeders=10),
        _candidate(seeders=50, size_bytes=2000),
    ]
    assert pick_best(c, _profile()).seeders == 50


def test_age_tiebreak_newer_wins():
    c = [
        _candidate(age_hours=100.0),
        _candidate(age_hours=10.0, size_bytes=2000),
    ]
    assert pick_best(c, _profile()).age_hours == 10.0


def test_size_tiebreak_smaller_wins_for_text():
    c = [
        _candidate(size_bytes=5000),
        _candidate(size_bytes=500),
    ]
    assert pick_best(c, _profile()).size_bytes == 500


def test_disallowed_format_excluded():
    c = [_candidate(fmt="M4B"), _candidate(fmt="PDF")]
    assert pick_best(c, _profile()).fmt == "PDF"  # M4B not allowed


def test_automated_beats_manual_tie():
    """A manual link (Anna's Archive) loses to an automated release."""
    c = [
        _candidate(manual=True),
        _candidate(manual=False),
    ]
    best = pick_best(c, _profile())
    assert best is not None and best.manual is False


def test_manual_bypasses_format_gate():
    """A manual link is eligible even with an unknown format."""
    c = [_candidate(fmt=None, manual=True)]
    assert pick_best(c, _profile()) is not None


def test_no_eligible_candidate_returns_none():
    c = [_candidate(fmt="M4B"), _candidate(fmt="MP3")]
    assert pick_best(c, _profile()) is None


def test_empty_candidates_returns_none():
    assert pick_best([], _profile()) is None


@pytest.mark.parametrize(
    "title",
    [
        "Dune - Frank Herbert (1965) EPUB",
        "Dune.EPUB",
        "Dune (2021) [ebook] EPUB",
    ],
)
def test_is_junk_accepts_good_titles(title):
    assert is_junk(title) is False


@pytest.mark.parametrize(
    "title",
    [
        "Dune - Frank Herbert (1965) EPUB [sample]",
        "Dune [Sample] AZW3",
        "Dune EPUB password",
        "Dune password-protected EPUB",
        "Dune scanned PDF.txt",
        "Dune [unknown] EPUB",
    ],
)
def test_is_junk_rejects_junk_titles(title):
    assert is_junk(title) is True


def test_normalize_candidate_parses_and_protocols():
    rel = _release(
        download_url="https://archive.org/download/x/x.epub",
        format="EPUB",
    )
    cand = normalize_candidate(rel, indexer_priority=50)
    assert cand is not None
    assert cand.parsed.title == "Dune"
    assert cand.parsed.author == "Frank Herbert"
    assert cand.protocol == "direct"
    assert cand.indexer_priority == 50


def test_normalize_candidate_usenet_protocol():
    rel = _release(download_url="http://nzbx/n/dune.nzb")
    cand = normalize_candidate(rel, indexer_priority=100)
    assert cand.protocol == "usenet"


def test_normalize_candidate_junk_is_none():
    rel = _release(title="Dune EPUB [sample]")
    assert normalize_candidate(rel, indexer_priority=100) is None


def test_candidates_fixture_corpus():
    """Table-driven junk filtering over the fixtures corpus (plan 2.3.3)."""
    path = Path(__file__).parent / "fixtures" / "candidates_fixtures.json"
    corpus = json.loads(path.read_text())
    for entry in corpus:
        title = entry["title"]
        assert is_junk(title) is entry["expected_junk"], title
