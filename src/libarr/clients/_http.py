"""Shared http plumbing for download clients: typed JSON helpers."""

from __future__ import annotations

from typing import Any

import httpx

from libarr.clients.base import DownloadError


class _HTTPClient:
    """Shared http plumbing with timeout + error wrapping."""

    def __init__(self, *, name: str, url: str, timeout: float = 20.0) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._http = httpx.Client(timeout=timeout, follow_redirects=True, verify=True)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = self._http.request(method, f"{self.url}{path}", **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            raise DownloadError(f"{self.name}: {exc}") from exc

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self._request("POST", path, **kwargs)
