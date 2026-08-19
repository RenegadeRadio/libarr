"""Phase 2.6.1 — subject normalization + alias thesaurus."""

import pytest

from libarr.metadata.subjects import ALIASES, normalize_subject, subject_slug


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sci-Fi", "science fiction"),
        ("sci-fi", "science fiction"),
        ("SF", "science fiction"),
        ("Science Fiction", "science fiction"),
        ("science-fiction", "science fiction"),
        ("Fantasy Fiction", "fantasy"),
        ("YA", "young adult"),
        ("Detective and Mystery Stories", "mystery"),
        ("Graphic Novels", "comics"),
        ("Romance Fiction", "romance"),
        ("Ecology", "Ecology"),  # no alias → unchanged
        ("Dune (Imaginary place)", "Dune (Imaginary place)"),
    ],
)
def test_normalize_subject(raw, expected):
    assert normalize_subject(raw) == expected


def test_subject_slug_uses_canonical():
    assert subject_slug("Sci-Fi") == "science-fiction"
    assert subject_slug("Science Fiction") == "science-fiction"
    assert subject_slug("Ecology") == "ecology"


def test_alias_table_shape():
    for canonical, aliases in ALIASES.items():
        assert canonical.lower() == canonical
        for alias in aliases:
            assert alias.lower() == alias
