"""Phase 2.2 — download client adapters (mocked HTTP fixtures per client)."""

import pytest
import respx
from httpx import Response

from libarr.clients.base import DownloadError
from libarr.clients.deluge import DelugeClient
from libarr.clients.nzbget import NZBGetClient
from libarr.clients.qbittorrent import QBittorrentClient
from libarr.clients.sabnzbd import SABnzbdClient
from libarr.clients.transmission import TransmissionClient

CATEGORY = "libarr"


# --- qBittorrent -------------------------------------------------------------


@respx.mock
def test_qbittorrent_add_url_and_list():
    respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=Response(200, text="Ok."))
    respx.post("http://qb:8080/api/v2/torrents/add").mock(return_value=Response(200, text="Ok."))
    respx.get("http://qb:8080/api/v2/torrents/info").mock(
        return_value=Response(
            200,
            json=[
                {
                    "hash": "abc123",
                    "name": "Dune - Frank Herbert (1965) EPUB",
                    "state": "uploading",
                    "progress": 1.0,
                    "size": 1000,
                    "save_path": "/downloads",
                }
            ],
        )
    )

    client = QBittorrentClient(name="qb", url="http://qb:8080", username="u", password="p")
    assert client.test() is True

    download_id = client.add_url("http://tracker/d/1.torrent", category=CATEGORY)
    assert download_id == "abc123"

    items = client.list_items(CATEGORY)
    assert len(items) == 1
    assert items[0].id == "abc123"
    assert items[0].status == "complete"
    assert items[0].progress == 100.0
    assert items[0].save_path == "/downloads"


@respx.mock
def test_qbittorrent_login_failure_raises():
    respx.post("http://qb:8080/api/v2/auth/login").mock(return_value=Response(200, text="Fails."))
    client = QBittorrentClient(name="qb", url="http://qb:8080", username="u", password="p")
    with pytest.raises(DownloadError):
        client.test()


# --- SABnzbd ----------------------------------------------------------------


@respx.mock
def test_sabnzbd_add_url_and_list():
    respx.get("http://sab:8080/api", params__contains={"mode": "get_config"}).mock(
        return_value=Response(200, json={"config": {"version": "4.0"}})
    )
    respx.get("http://sab:8080/api", params__contains={"mode": "addurl"}).mock(
        return_value=Response(200, json={"status": True, "nzo_ids": ["SAB1"]})
    )
    respx.get("http://sab:8080/api", params__contains={"mode": "queue"}).mock(
        return_value=Response(
            200,
            json={
                "queue": {
                    "slots": [
                        {
                            "nzo_id": "SAB1",
                            "filename": "Dune.epub",
                            "status": "Downloading",
                            "percentage": 50.0,
                            "category": "libarr",
                            "size": "1.0 G",
                        }
                    ]
                }
            },
        )
    )

    client = SABnzbdClient(name="sab", url="http://sab:8080", api_key="k")
    assert client.test() is True
    assert client.add_url("http://tracker/d/1.nzb", category=CATEGORY) == "SAB1"

    items = client.list_items(CATEGORY)
    assert items[0].id == "SAB1"
    assert items[0].status == "downloading"
    assert items[0].progress == 50.0


# --- Transmission ------------------------------------------------------------


@respx.mock
def test_transmission_add_url_and_list():
    # test() → session-get: 409 handshake, then retry succeeds; then add; then list.
    respx.post("http://tr:9091/transmission/rpc").mock(
        side_effect=[
            Response(409, headers={"X-Transmission-Session-Id": "SID123"}),
            Response(200, json={"result": "success", "arguments": {}}),
            Response(
                200,
                json={
                    "result": "success",
                    "arguments": {
                        "torrent-added": {"id": 7, "name": "Dune.epub", "hashString": "h7"}
                    },
                },
            ),
            Response(
                200,
                json={
                    "result": "success",
                    "arguments": {
                        "torrents": [
                            {
                                "id": 7,
                                "hashString": "h7",
                                "name": "Dune.epub",
                                "status": 4,
                                "percentDone": 0.5,
                                "totalSize": 1000,
                                "downloadDir": "/downloads",
                            }
                        ]
                    },
                },
            ),
        ],
    )

    client = TransmissionClient(name="tr", url="http://tr:9091", username="", password="")
    assert client.test() is True
    assert client.add_url("http://tracker/d/1.torrent", category=CATEGORY) == "h7"

    items = client.list_items(CATEGORY)
    assert items[0].id == "h7"
    assert items[0].status == "downloading"
    assert items[0].progress == 50.0
    assert items[0].save_path == "/downloads"


# --- Deluge -----------------------------------------------------------------


@respx.mock
def test_deluge_add_url_and_list():
    respx.post("http://de:8112/json").mock(
        side_effect=[
            Response(200, json={"result": True}),  # auth.login
            Response(200, json={"result": "hash1"}),  # core.add_torrent_url
            Response(
                200,
                json={
                    "result": {
                        "hash1": {
                            "name": "Dune.epub",
                            "state": "Seeding",
                            "progress": 100.0,
                            "total_size": 1000,
                            "save_path": "/downloads",
                        }
                    }
                },
            ),
        ]
    )

    client = DelugeClient(name="de", url="http://de:8112", password="p")
    assert client.test() is True
    assert client.add_url("http://tracker/d/1.torrent", category=CATEGORY) == "hash1"

    items = client.list_items(CATEGORY)
    assert items[0].status == "complete"
    assert items[0].save_path == "/downloads"


# --- NZBGet -----------------------------------------------------------------


@respx.mock
def test_nzbget_add_url_and_list():
    groups_json = [
        {
            "NZBID": 5,
            "Name": "Dune.epub",
            "Status": "DOWNLOADING",
            "FileSizeLo": 1000,
            "DestDir": "/downloads",
        }
    ]
    respx.post("http://nz:6789/jsonrpc").mock(
        side_effect=[
            Response(200, json={"result": "23.0", "id": 0}),  # version (test)
            Response(200, json={"result": True, "id": 0}),  # append
            Response(200, json={"result": groups_json, "id": 0}),  # listgroups (in add_url)
            Response(200, json={"result": groups_json, "id": 0}),  # listgroups (list_items)
        ]
    )

    client = NZBGetClient(name="nz", url="http://nz:6789", username="u", password="p")
    assert client.test() is True
    assert client.add_url("http://tracker/d/1.nzb", category=CATEGORY) == "5"

    items = client.list_items(CATEGORY)
    assert items[0].id == "5"
    assert items[0].status == "downloading"
    assert items[0].save_path == "/downloads"
