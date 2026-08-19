"""Anna's Archive as a manual-link indexer (Phase 3).

Anna's Archive has no public search API and its downloads are captcha-gated,
so automated grabbing is neither possible nor desirable. Instead this adapter
emits a single *manual* release per query: a link to the Anna's Archive search
page. The pipeline never auto-grabs manual releases — they surface in search
results and the user downloads them in a browser.

Search URL pattern: https://annas-archive.gl/search?q=<query>
"""

from __future__ import annotations

from urllib.parse import quote

from libarr.indexers.base import Release

SEARCH_URL = "https://annas-archive.gl/search"


class AnnasArchiveIndexer:
    kind = "annasarchive"

    def __init__(
        self,
        *,
        name: str = "Anna's Archive",
        url: str | None = None,
        api_key: str | None = None,
        categories: str = "",
    ) -> None:
        self.name = name

    def search(self, q: str) -> list[Release]:
        link = f"{SEARCH_URL}?q={quote(q)}"
        return [
            Release(
                title=f"{q} (Anna's Archive)",
                indexer_name=self.name,
                download_url=link,
                guid=f"annas:{q.lower()}",
                format=None,
                page_url=link,
                manual=True,
            )
        ]

    def recent(self, limit: int = 100) -> list[Release]:
        return []
