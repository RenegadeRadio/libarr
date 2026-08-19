"""Download client registry (plan 2.2): row → adapter instance."""

from __future__ import annotations

from typing import cast

from libarr.clients.base import DownloadClient, DownloadError
from libarr.clients.deluge import DelugeClient
from libarr.clients.nzbget import NZBGetClient
from libarr.clients.qbittorrent import QBittorrentClient
from libarr.clients.sabnzbd import SABnzbdClient
from libarr.clients.transmission import TransmissionClient
from libarr.models import DownloadClientRow

_CLIENTS = {
    client.kind: client
    for client in (
        QBittorrentClient,
        DelugeClient,
        TransmissionClient,
        SABnzbdClient,
        NZBGetClient,
    )
}

SUPPORTED_KINDS = sorted(_CLIENTS)
CLIENT_KINDS = sorted(_CLIENTS)


def build_client(row: DownloadClientRow) -> DownloadClient:
    client_cls = _CLIENTS.get(row.kind)
    if client_cls is None:
        raise DownloadError(f"unknown download client kind: {row.kind}")
    return cast(
        DownloadClient,
        client_cls(
            name=row.name,
            url=row.url or "",
            username=row.username or "",
            password=row.password or "",
            api_key=row.api_key or "",
        ),
    )
