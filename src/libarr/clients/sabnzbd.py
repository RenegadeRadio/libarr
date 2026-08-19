"""SABnzbd client — plan 2.2 (usenet)."""

from __future__ import annotations

from typing import Any, cast

from libarr.clients._http import _HTTPClient
from libarr.clients.base import CATEGORY, ClientItem, DownloadError


class SABnzbdClient(_HTTPClient):
    kind = "sabnzbd"

    def __init__(self, *, name: str, url: str, api_key: str = "", **_: object) -> None:
        super().__init__(name=name, url=url)
        self.api_key = api_key

    def _api(self, params: dict[str, str]) -> dict[str, Any]:
        params = {**params, "output": "json"}
        if self.api_key:
            params["apikey"] = self.api_key
        resp = self._get("/api", params=params)
        return cast(dict[str, Any], resp.json())

    def test(self) -> bool:
        body = self._api({"mode": "get_config", "name": "version"})
        return bool(body.get("config"))

    def add_url(self, url: str, category: str = CATEGORY) -> str:
        body = self._api({"mode": "addurl", "name": url, "cat": category})
        if not body.get("status"):
            raise DownloadError(f"{self.name}: add failed: {body}")
        ids = body.get("nzo_ids") or []
        return str(ids[0]) if ids else ""

    def list_items(self, category: str = CATEGORY) -> list[ClientItem]:
        body = self._api({"mode": "queue"})
        queue = body.get("queue") or {}
        items: list[ClientItem] = []
        for slot in queue.get("slots") or []:
            if category and slot.get("category") != category:
                continue
            status = slot.get("status") or ""
            state = (
                "complete"
                if status.lower().startswith("completed")
                else "error"
                if status.lower().startswith("failed")
                else "downloading"
            )
            items.append(
                ClientItem(
                    id=slot.get("nzo_id") or "",
                    name=slot.get("filename") or "",
                    status=state,
                    progress=float(slot.get("percentage") or 0.0),
                )
            )
        return items

    def remove(self, download_id: str, delete_files: bool = False) -> None:
        self._api({"mode": "queue", "name": download_id, "action": "delete"})
