"""qBittorrent client (Web API v2) — plan 2.2."""

from __future__ import annotations

from libarr.clients._http import _HTTPClient
from libarr.clients.base import CATEGORY, ClientItem, DownloadError


class QBittorrentClient(_HTTPClient):
    kind = "qbittorrent"

    def __init__(
        self, *, name: str, url: str, username: str = "", password: str = "", **_: object
    ) -> None:
        super().__init__(name=name, url=url)
        self.username = username
        self.password = password
        self._sid: str | None = None

    def _login(self) -> None:
        resp = self._post(
            "/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
        )
        if resp.text.strip() != "Ok.":
            raise DownloadError(f"{self.name}: login failed ({resp.text.strip()})")
        self._sid = resp.cookies.get("SID")

    def _auth_headers(self) -> dict[str, str]:
        return {"Cookie": f"SID={self._sid}"} if self._sid else {}

    def _ensure_login(self) -> None:
        if self._sid is None:
            self._login()

    def test(self) -> bool:
        self._login()
        return True

    def add_url(self, url: str, category: str = CATEGORY) -> str:
        self._ensure_login()
        resp = self._post(
            "/api/v2/torrents/add",
            data={"urls": url, "category": category},
            headers=self._auth_headers(),
        )
        if resp.text.strip() != "Ok.":
            raise DownloadError(f"{self.name}: add failed ({resp.text.strip()})")
        # The added hash is not returned; read it back from the queue.
        items = self.list_items(category)
        if not items:
            raise DownloadError(f"{self.name}: added torrent not found in queue")
        return items[0].id

    def list_items(self, category: str = CATEGORY) -> list[ClientItem]:
        self._ensure_login()
        resp = self._get(
            "/api/v2/torrents/info",
            params={"category": category},
            headers=self._auth_headers(),
        )
        items: list[ClientItem] = []
        for tor in resp.json():
            state = tor.get("state") or ""
            complete = state.startswith(("uploading", "stalledUP", "forcedUP", "pausedUP"))
            status = "complete" if complete else "error" if state == "error" else "downloading"
            items.append(
                ClientItem(
                    id=tor.get("hash") or "",
                    name=tor.get("name") or "",
                    status=status,
                    progress=float(tor.get("progress") or 0.0) * 100.0,
                    size_bytes=tor.get("size"),
                    save_path=tor.get("save_path"),
                )
            )
        return items

    def remove(self, download_id: str, delete_files: bool = False) -> None:
        self._ensure_login()
        self._post(
            "/api/v2/torrents/delete",
            data={"hashes": download_id, "deleteFiles": "true" if delete_files else "false"},
            headers=self._auth_headers(),
        )
