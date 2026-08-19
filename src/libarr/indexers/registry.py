"""Indexer registry (plan 2.1.1): Indexer row → client instance."""

from __future__ import annotations

from typing import cast

from libarr.indexers.base import IndexerClient, IndexerError
from libarr.indexers.gutenberg import GutenbergIndexer
from libarr.indexers.openlibrary import OpenLibraryIndexer
from libarr.indexers.torznab import TorznabIndexer
from libarr.models import Indexer

_CLIENTS = {
    client.kind: client for client in (TorznabIndexer, GutenbergIndexer, OpenLibraryIndexer)
}

SUPPORTED_KINDS = sorted(_CLIENTS)


def build_indexer(row: Indexer) -> IndexerClient:
    client_cls = _CLIENTS.get(row.kind)
    if client_cls is None:
        raise IndexerError(f"unknown indexer kind: {row.kind}")
    return cast(
        IndexerClient,
        client_cls(
            name=row.name,
            url=row.url,
            api_key=row.api_key,
            categories=row.categories,
        ),
    )
