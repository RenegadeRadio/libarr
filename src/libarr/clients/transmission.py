"""Transmission client (RPC) — plan 2.2."""

from __future__ import annotations

from typing import Any

import httpx

from libarr.clients._http import _HTTPClient
from libarr.clients.base import CATEGORY, ClientItem, DownloadError

_RPC_PATH = "/transmission/rpc"

# Transmission numeric status codes.
_TR_STATUS = {
    0: "queued",  # stopped
    1: "downloading",  # check pending
    2: "downloading",  # checking
    3: "queued",  # download pending
    4: "downloading",
    5: "queued",  # seed pending
    6: "complete",  # seeding
}


class TransmissionClient(_HTTPClient):
    kind = "transmission"

    def __init__(
        self, *, name: str, url: str, username: str = "", password: str = "", **_: object
    ) -> None:
        super().__init__(name=name, url=url)
        self.username = username
        self.password = password
        self._session_id: str | None = None

    def _rpc(self, method: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"X-Transmission-Session-Id": self._session_id} if self._session_id else {}
        rpc_payload: dict[str, Any] = {"method": method, "arguments": arguments or {}}
        try:
            if self.username:
                resp = self._http.post(
                    f"{self.url}{_RPC_PATH}",
                    json=rpc_payload,
                    headers=headers,
                    auth=(self.username, self.password),
                )
            else:
                resp = self._http.post(f"{self.url}{_RPC_PATH}", json=rpc_payload, headers=headers)
        except httpx.HTTPError as exc:
            raise DownloadError(f"{self.name}: {exc}") from exc
        if resp.status_code == 409:
            # Session handshake: retry once with the session id.
            self._session_id = resp.headers.get("X-Transmission-Session-Id", "")
            return self._rpc(method, arguments)
        if resp.status_code != 200:
            raise DownloadError(f"{self.name}: HTTP {resp.status_code}")
        body = resp.json()
        if body.get("result") != "success":
            raise DownloadError(f"{self.name}: {body.get('result')}")
        return body.get("arguments") or {}

    def test(self) -> bool:
        self._rpc("session-get")
        return True

    def add_url(self, url: str, category: str = CATEGORY) -> str:
        args = self._rpc("torrent-add", {"filename": url})
        added = args.get("torrent-added") or args.get("torrent-duplicate") or {}
        return added.get("hashString") or str(added.get("id") or "")

    def list_items(self, category: str = CATEGORY) -> list[ClientItem]:
        args = self._rpc(
            "torrent-get",
            {
                "fields": ["id", "name", "status", "percentDone", "totalSize", "downloadDir"],
                "ids": "recently-active",
            },
        )
        items: list[ClientItem] = []
        for tor in args.get("torrents") or []:
            code = int(tor.get("status") or 0)
            items.append(
                ClientItem(
                    id=tor.get("hashString") or str(tor.get("id") or ""),
                    name=tor.get("name") or "",
                    status=_TR_STATUS.get(code, "downloading"),
                    progress=float(tor.get("percentDone") or 0.0) * 100.0,
                    size_bytes=tor.get("totalSize"),
                    save_path=tor.get("downloadDir"),
                )
            )
        return items

    def remove(self, download_id: str, delete_files: bool = False) -> None:
        self._rpc(
            "torrent-remove",
            {"ids": [download_id], "delete-local-data": delete_files},
        )
