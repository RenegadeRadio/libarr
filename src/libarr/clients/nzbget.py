"""NZBGet client (JSON-RPC) — plan 2.2 (usenet)."""

from __future__ import annotations

from typing import Any, cast

from libarr.clients._http import _HTTPClient
from libarr.clients.base import CATEGORY, ClientItem, DownloadError


class NZBGetClient(_HTTPClient):
    kind = "nzbget"

    def __init__(
        self, *, name: str, url: str, username: str = "", password: str = "", **_: object
    ) -> None:
        super().__init__(name=name, url=url)
        self.username = username
        self.password = password

    def _rpc(self, method: str, params: list[Any] | None = None) -> object:
        auth = (self.username, self.password) if self.username else None
        resp = self._post(
            "/jsonrpc",
            json={"method": method, "params": params or [], "id": 0},
            auth=auth,
        )
        body = resp.json()
        if body.get("error") is not None:
            raise DownloadError(f"{self.name}: {body['error']}")
        return body.get("result")

    def test(self) -> bool:
        result = self._rpc("version")
        return bool(result)

    def add_url(self, url: str, category: str = CATEGORY) -> str:
        result = self._rpc("append", ["libarr", url, category, 0, False, ""])
        if not result:
            raise DownloadError(f"{self.name}: append failed")
        # NZBGet returns True; look the group back up to learn its id.
        groups = cast(list[dict[str, Any]], self._rpc("listgroups", [0, 100]) or [])
        for group in groups:
            if group.get("NZBID") is not None:
                return str(group["NZBID"])
        return ""

    def list_items(self, category: str = CATEGORY) -> list[ClientItem]:
        groups = cast(list[dict[str, Any]], self._rpc("listgroups", [0, 200]) or [])
        items: list[ClientItem] = []
        for group in groups:
            status = group.get("Status") or ""
            state = (
                "complete"
                if status in ("SUCCESS", "COMPLETED")
                else "error"
                if status == "FAILED"
                else "downloading"
            )
            items.append(
                ClientItem(
                    id=str(group.get("NZBID") or ""),
                    name=group.get("Name") or "",
                    status=state,
                    progress=0.0,
                    size_bytes=group.get("FileSizeLo"),
                    save_path=group.get("DestDir"),
                )
            )
        return items

    def remove(self, download_id: str, delete_files: bool = False) -> None:
        self._rpc("editqueue", ["GroupFinalDelete", [int(download_id)]])
