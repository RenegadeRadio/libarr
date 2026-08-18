"""Phase 1.3 — book filename parser: title/author/year/series/ISBN extraction."""

import pytest

from libarr.acquisition.parser import ParsedName, parse_book_filename


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        # Title - Author with year
        (
            "The Stand - Stephen King (1990).epub",
            ParsedName(title="The Stand", author="Stephen King", year=1990),
        ),
        # Series - #position - Title - Author
        (
            "Dark Tower - 03 - The Waste Lands - Stephen King.epub",
            ParsedName(
                title="The Waste Lands",
                author="Stephen King",
                series="Dark Tower",
                series_position=3,
            ),
        ),
        # ISBN-prefixed
        (
            "9780061120084 - The Road - Cormac McCarthy.epub",
            ParsedName(
                title="The Road",
                author="Cormac McCarthy",
                isbn="9780061120084",
            ),
        ),
        # Bare title, underscores, no extension
        (
            "Neuromancer.mobi",
            ParsedName(title="Neuromancer"),
        ),
        # Year in brackets, no author
        (
            "Dune [1965].pdf",
            ParsedName(title="Dune", year=1965),
        ),
        # Author with dots (release-style), series colon form
        (
            "Mistborn - The Final Empire - Brandon.Sanderson.azw3",
            ParsedName(
                title="The Final Empire",
                author="Brandon.Sanderson",
                series="Mistborn",
            ),
        ),
        # Group tags to strip
        (
            "[TeamX] The Great Gatsby (1925) - F. Scott Fitzgerald.epub",
            ParsedName(title="The Great Gatsby", author="F. Scott Fitzgerald", year=1925),
        ),
        # Edition hint preserved
        (
            "Leviathan Wakes - Unabridged - James S.A. Corey.m4b",
            ParsedName(
                title="Leviathan Wakes",
                author="James S.A. Corey",
                edition_hint="Unabridged",
            ),
        ),
        # Non-book file should not parse
        ("cover.jpg", None),
        ("notes.txt", None),
        ("", None),
    ],
)
def test_parse_book_filename(filename, expected):
    assert parse_book_filename(filename) == expected
