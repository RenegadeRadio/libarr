"""Download client layer (plan 2.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

CATEGORY = "libarr"


class DownloadError(Exception):
    """Raised when a download client fails — per-client isolation."""


@dataclass(slots=True)
class ClientItem:
    """A download as reported by a client, normalized."""

    id: str
    name: str
    status: str  # queued | downloading | complete | error | removed
    progress: float  # 0..100
    size_bytes: int | None = None
    save_path: str | None = None


class DownloadClient(Protocol):
    name: str

    def test(self) -> bool: ...

    def add_url(self, url: str, category: str = CATEGORY) -> str: ...

    def list_items(self, category: str = CATEGORY) -> list[ClientItem]: ...

    def remove(self, download_id: str, delete_files: bool = False) -> None: ...


def _status(*, state: str, progress: float, complete_states: tuple[str, ...]) -> str:
    if state in complete_states:
        return "complete"
    if state in ("error", "failed", "Error", "FAILED"):
        return "error"
    if progress >= 100.0:
        return "complete"
    return "downloading"
