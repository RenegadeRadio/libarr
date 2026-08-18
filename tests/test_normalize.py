"""Normalization utilities: text folding, slugs, ISBN validation/conversion."""


from libarr.metadata.normalize import normalize_isbn, normalize_text, slugify


def test_normalize_text_folds_case_and_punctuation():
    assert normalize_text("The Stand (Unabridged)!") == "the stand unabridged"
    assert normalize_text("  Neuromancer  ") == "neuromancer"
    assert normalize_text("Æsop's Fables") == "aesop s fables"


def test_slugify():
    assert slugify("Science Fiction") == "science-fiction"
    assert slugify("   Dune: Messiah! ") == "dune-messiah"


def test_isbn10_to_13_conversion():
    assert normalize_isbn("0-306-40615-2") == "9780306406157"


def test_isbn13_valid_passes():
    assert normalize_isbn("9780306406157") == "9780306406157"


def test_invalid_isbn_returns_none():
    assert normalize_isbn("9780306406158") is None
    assert normalize_isbn("not-an-isbn") is None
    assert normalize_isbn("123456789012") is None
