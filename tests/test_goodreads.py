"""Goodreads public rating enrichment and recommendation balancing."""

import respx
from httpx import Response

from libarr.chat import _rank_works
from libarr.discovery import DiscoveryWork
from libarr.goodreads import _CACHE, lookup_rating, parse_search_results

SEARCH_HTML = """
<table>
<tr itemscope itemtype="http://schema.org/Book">
  <td><a class="bookTitle" itemprop="url" href="/book/show/375802.Ender_s_Game?q=x">
    <span itemprop='name'>Ender's Game</span></a>
  <a class="authorName"><span itemprop="name">Orson Scott Card</span></a>
  <span class="minirating">4.31 avg rating &mdash; 1,445,210 ratings</span></td>
</tr>
</table>
"""


def _work(title: str, year: int) -> DiscoveryWork:
    return DiscoveryWork(
        title=title,
        author="Writer",
        year=year,
        subjects=["Espionage"],
        source="openlibrary",
        source_key=title,
    )


def test_parse_goodreads_public_rating_metadata():
    results = parse_search_results(SEARCH_HTML)

    assert results == [
        {
            "title": "Ender's Game",
            "author": "Orson Scott Card",
            "average": 4.31,
            "count": 1445210,
            "url": "https://www.goodreads.com/book/show/375802.Ender_s_Game",
        }
    ]


@respx.mock
def test_lookup_goodreads_rating_matches_title_and_author():
    _CACHE.clear()
    respx.get("https://www.goodreads.com/search").mock(return_value=Response(200, text=SEARCH_HTML))

    rating = lookup_rating("Ender's Game", "Orson Scott Card")

    assert rating is not None
    assert rating.average == 4.31
    assert rating.count == 1445210


def test_ranking_keeps_recent_modern_and_classic_variety():
    works = [
        *[_work(f"Recent {index}", 2020 + index) for index in range(6)],
        *[_work(f"Modern {index}", 2000 + index) for index in range(6)],
        *[_work(f"Classic {index}", 1960 + index) for index in range(6)],
    ]

    ranked = _rank_works(works, limit=12, use_goodreads=False)
    years = [work.year for work, _rating in ranked]

    assert len(ranked) == 12
    assert sum(year >= 2016 for year in years) >= 4
    assert sum(1990 <= year < 2016 for year in years) >= 4
    assert sum(year < 1990 for year in years) >= 2
