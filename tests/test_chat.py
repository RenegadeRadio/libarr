"""Phase 4.5 — the chat assistant: natural language → discovery actions."""

import pytest
import respx
from httpx import Response

from libarr.chat import parse_intent

# --- intent parsing --------------------------------------------------------------


def test_parse_similar_to_show():
    intent = parse_intent("i am looking for books that are similar to rubicon")
    assert intent.kind == "similar"
    assert intent.target == "rubicon"
    assert "espionage" in intent.themes


def test_parse_similar_to_multiple_shows_with_parenthetical():
    intent = parse_intent(
        "i am looking for books that are similar to rubicon/rabbithole (tv series)"
    )
    assert intent.kind == "similar"
    assert "rubicon/rabbithole" in intent.target
    assert "conspiracy" in intent.themes
    assert "espionage" in intent.themes
    assert "thrillers" in intent.themes


def test_parse_author_query():
    intent = parse_intent("find me books by ursula k le guin")
    assert intent.kind == "author"
    assert "le guin" in intent.query


def test_parse_genre_and_decade():
    intent = parse_intent("sci-fi books from the 1980s")
    assert intent.genre == "science fiction"
    assert intent.year_min == 1980
    assert intent.year_max == 1989


def test_parse_request_intent():
    intent = parse_intent("request dune by frank herbert")
    assert intent.kind == "request"
    assert "dune" in intent.query


def test_show_themes_knowledge_base():
    from libarr.chat import show_themes

    assert "espionage" in show_themes("rubicon")
    assert "conspiracy" in show_themes("rabbithole")


def test_knowledge_base_is_complete_and_lowercase():
    from libarr.chat import SHOW_THEMES

    assert len(SHOW_THEMES) >= 100
    for name, themes in SHOW_THEMES.items():
        assert themes, f"{name} has no themes"
        assert name == name.lower(), f"{name} not lowercase"
        for theme in themes:
            assert theme == theme.lower(), f"{name}: theme '{theme}' not lowercase"


@pytest.mark.parametrize(
    ("show", "expected"),
    [
        ("severance", "dystopia"),
        ("battlestar galactica", "space opera"),
        ("game of thrones", "epic fantasy"),
        ("the crown", "royal family"),
        ("peaky blinders", "gangsters"),
        ("breaking bad", "moral descent"),
        ("the last of us", "post-apocalyptic"),
        ("ted lasso", "optimism"),
        ("chernobyl", "disaster"),
        ("twin peaks", "surrealism"),
    ],
)
def test_knowledge_base_spot_checks(show, expected):
    from libarr.chat import show_themes

    assert expected in show_themes(show), f"{show} missing theme {expected}"


# --- chat handling (heuristic path, no API key) ----------------------------------


@respx.mock
def test_handle_similar_show_returns_books(client, db, monkeypatch):
    client, db = client
    monkeypatch.delenv("LIBARR_CHAT_API_KEY", raising=False)

    ol_json = {
        "numFound": 2,
        "docs": [
            {
                "key": "/works/OL1W",
                "title": "The Quiet American",
                "author_name": ["Graham Greene"],
                "first_publish_year": 1955,
                "subject": ["Conspiracy", "Espionage"],
            },
            {
                "key": "/works/OL2W",
                "title": "The Spy Who Came in from the Cold",
                "author_name": ["John le Carré"],
                "first_publish_year": 1963,
                "subject": ["Espionage"],
            },
        ],
    }
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=ol_json)
    )

    resp = client.post(
        "/api/v1/chat",
        json={"message": "i am looking for books that are similar to rabbithole"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"]
    assert len(body["suggestions"]) >= 1
    titles = {s["title"] for s in body["suggestions"]}
    assert "The Spy Who Came in from the Cold" in titles


@respx.mock
def test_handle_genre_decade_request(client, db, monkeypatch):
    client, db = client
    monkeypatch.delenv("LIBARR_CHAT_API_KEY", raising=False)

    ol_json = {
        "numFound": 1,
        "docs": [
            {
                "key": "/works/OL9W",
                "title": "Neuromancer",
                "author_name": ["William Gibson"],
                "first_publish_year": 1984,
                "subject": ["Science fiction"],
            },
        ],
    }
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=ol_json)
    )

    resp = client.post("/api/v1/chat", json={"message": "sci-fi books from the 1980s"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(s["title"] == "Neuromancer" for s in body["suggestions"])


@respx.mock
def test_handle_author_query(client, db, monkeypatch):
    client, db = client
    monkeypatch.delenv("LIBARR_CHAT_API_KEY", raising=False)

    ol_json = {
        "numFound": 1,
        "docs": [
            {
                "key": "/works/OL3W",
                "title": "The Left Hand of Darkness",
                "author_name": ["Ursula K. Le Guin"],
                "first_publish_year": 1969,
                "subject": ["Science fiction"],
            },
        ],
    }
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=ol_json)
    )

    resp = client.post("/api/v1/chat", json={"message": "find me books by ursula k le guin"})
    body = resp.json()
    assert any(s["title"] == "The Left Hand of Darkness" for s in body["suggestions"])


@respx.mock
def test_handle_similar_uses_top_themes_with_fallback(client, db, monkeypatch):
    """Long theme lists are truncated; empty results retry with theme #1."""
    client, db = client
    monkeypatch.delenv("LIBARR_CHAT_API_KEY", raising=False)

    calls = []

    def _handler(request):
        calls.append(request.url.params.get("q"))
        if len(calls) == 1:
            return Response(200, json={"numFound": 0, "docs": []})
        return Response(
            200,
            json={
                "numFound": 1,
                "docs": [
                    {
                        "key": "/works/OL1W",
                        "title": "The Quiet American",
                        "author_name": ["Graham Greene"],
                        "first_publish_year": 1955,
                        "subject": ["Conspiracy"],
                    },
                ],
            },
        )

    respx.get(url__startswith="https://openlibrary.org/search.json").mock(side_effect=_handler)

    resp = client.post("/api/v1/chat", json={"message": "similar to rubicon"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(calls) == 2  # full themes → single-theme fallback
    assert "conspiracy" in calls[0]
    assert "conspiracy" in calls[1]
    assert body["suggestions"]


# --- LLM-backed path ---------------------------------------------------------------


@respx.mock
def test_handle_with_llm_uses_model_json(client, db, monkeypatch):
    client, db = client
    monkeypatch.setenv("LIBARR_CHAT_API_KEY", "sk-test")
    monkeypatch.setenv("LIBARR_CHAT_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LIBARR_CHAT_MODEL", "test-model")

    llm_json = {
        "themes": ["political thrillers", "intelligence services"],
        "genre": None,
        "year_min": None,
        "year_max": None,
        "title": None,
    }
    respx.post("https://llm.example/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={"choices": [{"message": {"content": __import__("json").dumps(llm_json)}}]},
        )
    )
    ol_json = {
        "numFound": 1,
        "docs": [
            {
                "key": "/works/OL5W",
                "title": "Tinker Tailor Soldier Spy",
                "author_name": ["John le Carré"],
                "first_publish_year": 1974,
                "subject": ["Intelligence service"],
            },
        ],
    }
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=ol_json)
    )

    resp = client.post("/api/v1/chat", json={"message": "books similar to the tv show rubicon"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(s["title"] == "Tinker Tailor Soldier Spy" for s in body["suggestions"])


@respx.mock
def test_llm_garbage_falls_back_to_heuristics(client, db, monkeypatch):
    client, db = client
    monkeypatch.setenv("LIBARR_CHAT_API_KEY", "sk-test")
    monkeypatch.setenv("LIBARR_CHAT_BASE_URL", "https://llm.example/v1")

    # LLM returns non-JSON garbage → must not crash; fall back to heuristics.
    respx.post("https://llm.example/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "sure!"}}]})
    )
    ol_json = {
        "numFound": 1,
        "docs": [
            {
                "key": "/works/OL1W",
                "title": "The Quiet American",
                "author_name": ["Graham Greene"],
                "first_publish_year": 1955,
                "subject": ["Conspiracy"],
            },
        ],
    }
    respx.get(url__startswith="https://openlibrary.org/search.json").mock(
        return_value=Response(200, json=ol_json)
    )

    resp = client.post("/api/v1/chat", json={"message": "similar to rubicon"})
    assert resp.status_code == 200
    assert resp.json()["suggestions"]
