"""Best-effort Goodreads rating enrichment from public search metadata.

Goodreads no longer offers new public API access. Its public search results
still expose title, author, average rating, and rating count. This adapter is
deliberately optional, cached, and failure-tolerant: recommendations continue
without ratings if Goodreads changes the page or rejects a request.
"""

from __future__ import annotations

import html
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import httpx

from libarr.metadata.normalize import normalize_text

SEARCH_URL = "https://www.goodreads.com/search"
USER_AGENT = "Mozilla/5.0 (compatible; Libarr/0.1; book metadata lookup)"
_CACHE_TTL = 24 * 60 * 60
_CACHE_LOCK = threading.Lock()
_ROW_RE = re.compile(
    r'<tr\s+itemscope\s+itemtype="http://schema\.org/Book">(.*?)</tr>', re.S | re.I
)
_TITLE_RE = re.compile(
    r'<a\s+class="bookTitle"[^>]*href="([^"]+)"[^>]*>.*?'
    r"<span[^>]*itemprop=['\"]name['\"][^>]*>(.*?)</span>",
    re.S | re.I,
)
_AUTHOR_RE = re.compile(
    r'<a\s+class="authorName"[^>]*>.*?'
    r'<span\s+itemprop="name"[^>]*>(.*?)</span>',
    re.S | re.I,
)
_RATING_RE = re.compile(r"([0-5](?:\.\d+)?)\s+avg rating\s+&mdash;\s+([\d,]+)\s+ratings")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class GoodreadsRating:
    average: float
    count: int
    url: str

    @property
    def rank_score(self) -> float:
        """Bayesian-ish confidence: rating plus up to 0.5 for vote volume."""
        return self.average + min(0.5, math.log10(self.count + 1) / 10)


_CACHE: dict[tuple[str, str], tuple[float, GoodreadsRating | None]] = {}


def _text(value: str) -> str:
    return html.unescape(_TAG_RE.sub("", value)).strip()


def parse_search_results(page: str) -> list[dict[str, Any]]:
    """Extract only the stable schema.org/search rating fields."""
    results: list[dict[str, Any]] = []
    for row in _ROW_RE.findall(page):
        title_match = _TITLE_RE.search(row)
        rating_match = _RATING_RE.search(row)
        if title_match is None or rating_match is None:
            continue
        author_match = _AUTHOR_RE.search(row)
        href = html.unescape(title_match.group(1))
        results.append(
            {
                "title": _text(title_match.group(2)),
                "author": _text(author_match.group(1)) if author_match else "",
                "average": float(rating_match.group(1)),
                "count": int(rating_match.group(2).replace(",", "")),
                "url": f"https://www.goodreads.com{href.split('?', 1)[0]}",
            }
        )
    return results


def _best_match(
    results: list[dict[str, Any]], title: str, author: str | None
) -> GoodreadsRating | None:
    wanted_title = normalize_text(title)
    wanted_author = normalize_text(author or "")
    best: tuple[float, dict[str, Any]] | None = None
    for result in results:
        result_title = normalize_text(str(result["title"]))
        title_score = SequenceMatcher(None, wanted_title, result_title).ratio()
        result_author = normalize_text(str(result["author"]))
        author_score = (
            SequenceMatcher(None, wanted_author, result_author).ratio() if wanted_author else 1.0
        )
        score = title_score * 0.75 + author_score * 0.25
        if title_score >= 0.72 and author_score >= 0.45 and (best is None or score > best[0]):
            best = (score, result)
    if best is None:
        return None
    result = best[1]
    return GoodreadsRating(
        average=float(result["average"]), count=int(result["count"]), url=str(result["url"])
    )


def lookup_rating(title: str, author: str | None) -> GoodreadsRating | None:
    """Look up one work, returning None on any network or page-shape failure."""
    key = (normalize_text(title), normalize_text(author or ""))
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and now - cached[0] < _CACHE_TTL:
            return cached[1]
    try:
        response = httpx.get(
            SEARCH_URL,
            params={"q": f"{title} {author or ''}".strip()},
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=8,
        )
        response.raise_for_status()
        rating = _best_match(parse_search_results(response.text), title, author)
    except (httpx.HTTPError, ValueError):
        rating = None
    with _CACHE_LOCK:
        _CACHE[key] = (now, rating)
    return rating


def lookup_ratings(
    books: list[tuple[str, str | None]], *, workers: int = 6
) -> dict[tuple[str, str | None], GoodreadsRating]:
    """Enrich a candidate pool concurrently, bounded to be polite and responsive."""
    unique = list(dict.fromkeys(books))
    with ThreadPoolExecutor(max_workers=min(workers, len(unique) or 1)) as pool:
        ratings = pool.map(lambda book: lookup_rating(*book), unique)
    return {
        book: rating for book, rating in zip(unique, ratings, strict=True) if rating is not None
    }
