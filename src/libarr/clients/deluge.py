"""Deluge client (JSON-RPC) — plan 2.2."""

from __future__ import annotations

from typing import Any

from libarr.clients._http import _HTTPClient
from libarr.clients.base import CATEGORY, ClientItem, DownloadError


class DelugeClient(_HTTPClient):
    kind = "deluge"

    def __init__(self, *, name: str, url: str, password: str = "", **_: object) -> None:
        super().__init__(name=name, url=url)
        self.password = password
        self._logged_in = False

    def _rpc(self, method: str, params: list[Any] | None = None) -> object:
        resp = self._post(
            "/json",
            json={"method": method, "params": params or [], "id": 1},
        )
        body = resp.json()
        if body.get("error") is not None:
            raise DownloadError(f"{self.name}: {body['error']}")
        return body.get("result")

    def _ensure_login(self) -> None:
        if self._logged_in:
            return
        result = self._rpc("auth.login", [self.password])
        if not result:
            raise DownloadError(f"{self.name}: login failed")
        self._logged_in = True

    def test(self) -> bool:
        self._ensure_login()
        return True

    def add_url(self, url: str, category: str = CATEGORY) -> str:
        self._ensure_login()
        result = self._rpc("core.add_torrent_url", [url, {}])
        return str(result or "")

    def list_items(self, category: str = CATEGORY) -> list[ClientItem]:
        self._ensure_login()
        result = self._rpc(
            "core.get_torrents_status",
            [{}, ["name", "state", "progress", "total_size", "save_path"]],
        )
        items: list[ClientItem] = []
        torrents = (result or {}).items() if isinstance(result, dict) else []
        for torrent_id, tor in torrents:
            state = tor.get("state") or ""
            status = (
                "complete"
                if state in ("Seeding", "Finished")
                else "error"
                if state == "Error"
                else "downloading"
            )
            items.append(
                ClientItem(
                    id=str(torrent_id),
                    name=tor.get("name") or "",
                    status=status,
                    progress=float(tor.get("progress") or 0.0) * 100.0,
                    size_bytes=tor.get("total_size"),
                    save_path=tor.get("save_path"),
                )
            )
        return items

    def remove(self, download_id: str, delete_files: bool = False) -> None:
        self._ensure_login()
        self._rpc("core.remove_torrent", [download_id, delete_files])
