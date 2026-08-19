"""Subject normalization + alias thesaurus (plan 2.6.1, §4.4).

Keeps genre facets clean: "Sci-Fi", "sci-fi", "SF" and "Science Fiction" all
collapse to one canonical slug; provider subjects merge instead of duplicating.
"""

from __future__ import annotations

from libarr.metadata.normalize import slugify

# Canonical name → aliases (lowercase, bare).
ALIASES: dict[str, tuple[str, ...]] = {
    "science fiction": ("sci-fi", "sci fi", "sf", "science-fiction", "scifi"),
    "fantasy": ("fantasy fiction", "fantasy literature"),
    "horror": ("horror fiction", "horror stories"),
    "mystery": ("mystery fiction", "detective and mystery stories"),
    "thriller": ("thrillers", "suspense fiction"),
    "romance": ("romance fiction", "love stories"),
    "historical fiction": ("historical novels",),
    "young adult": ("ya", "young adult fiction"),
    "children's literature": ("children's stories", "childrens literature", "children's fiction"),
    "nonfiction": ("non-fiction", "non fiction", "nonfiction literature"),
    "biography": ("biographies", "autobiography"),
    "poetry": ("poetry collections", "poems"),
    "drama": ("plays", "theater"),
    "comics": ("graphic novels", "comic books"),
    "short stories": ("short story collections", "short fiction"),
}


def normalize_subject(name: str) -> str:
    """Canonical subject name via the alias thesaurus (case/punct-insensitive)."""
    key = name.strip().lower().replace("  ", " ")
    for canonical, aliases in ALIASES.items():
        if key == canonical or key in aliases:
            return canonical
    return name.strip()


def subject_slug(name: str) -> str:
    return slugify(normalize_subject(name))
