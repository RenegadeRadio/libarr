"""The chat assistant (Phase 4.5): natural language → discovery actions.

Hybrid design:
  * With LIBARR_CHAT_API_KEY set, an OpenAI-compatible model extracts the
    discovery intent (themes/genre/years/title/author) as JSON.
  * Without a key (or when the model misbehaves), a heuristic parser plus a
    curated show→themes knowledge base handles the same intents.

Suggestions are pure discovery results — nothing is imported until the user
picks a book and requests it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.orm import Session

from libarr.config import Settings
from libarr.discovery import search_works

# Curated "what is this show about" knowledge base for common TV series.
SHOW_THEMES: dict[str, list[str]] = {
    "rubicon": ["conspiracy", "espionage", "intelligence services", "paranoia"],
    "rabbithole": ["conspiracy", "corporate espionage", "paranoia", "thrillers"],
    "the wire": ["crime", "police", "urban drama", "institutional failure"],
    "dark": ["time travel", "mystery", "small town secrets", "science fiction"],
    "severance": ["dystopia", "corporate satire", "identity", "science fiction"],
    "the expanse": ["space opera", "political intrigue", "hard science fiction"],
    "twin peaks": ["mystery", "surrealism", "small town secrets"],
    "house of cards": ["political intrigue", "power", "ambition"],
    "true detective": ["crime", "detective", "gothic", "philosophy"],
    "fargo": ["crime", "dark comedy", "midwest noir"],
    "mr robot": ["hacking", "paranoia", "conspiracy", "technology"],
    "the americans": ["espionage", "cold war", "spies"],
    "westworld": ["artificial intelligence", "dystopia", "philosophy"],
    "black mirror": ["dystopia", "technology", "speculative fiction"],
}

_GENRES = {
    "sci-fi": "science fiction",
    "scifi": "science fiction",
    "science fiction": "science fiction",
    "sf": "science fiction",
    "fantasy": "fantasy",
    "mystery": "mystery",
    "thriller": "thrillers",
    "horror": "horror",
    "romance": "romance",
    "history": "history",
    "biography": "biography",
    "non-fiction": "nonfiction",
    "nonfiction": "nonfiction",
}

_SIMILAR_RE = re.compile(r"\bsimilar to\s+([a-z0-9&'.: /\-()]+?)(?:\s*[,.;!?]|$)", re.I)
_AUTHOR_RE = re.compile(r"\bby\s+([a-z][a-z' .-]+)$", re.I)
_DECADE_RE = re.compile(r"(?:from|in|the)?\s*(?:the\s+)?(19|20)(\d\d)s?\b", re.I)
_YEARS_RE = re.compile(r"\b(19|20)\d\d\b")


@dataclass(slots=True)
class ChatIntent:
    kind: str = "search"  # similar | author | genre | request | search
    query: str = ""
    target: str = ""
    genre: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    themes: list[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def parse_intent(message: str) -> ChatIntent:
    """Heuristic intent extraction (the no-key fallback)."""
    text = _normalize(message)
    intent = ChatIntent()
    is_request = bool(re.search(r"^(?:request|get me|i want|add)\b", text))

    match = _SIMILAR_RE.search(text)
    if match:
        intent.kind = "similar"
        raw = re.sub(r"\((?:tv|tv series|series|show)\)", "", match.group(1)).strip()
        intent.target = raw
        # "rubicon/rabbithole" → the union of both shows' themes
        parts = [p.strip() for p in raw.split("/") if p.strip()]
        for part in parts:
            for theme in show_themes(part):
                if theme not in intent.themes:
                    intent.themes.append(theme)
        if not intent.themes:
            intent.query = raw  # unknown show: search the name itself

    author = _AUTHOR_RE.search(text)
    if author:
        intent.query = author.group(1).strip()
        intent.kind = "request" if is_request else "author"
        if is_request:
            # keep the whole subject ("dune by frank herbert") for the search
            intent.query = re.sub(r"^(?:request|get me|i want|add)\s*", "", text)

    for token, canonical in _GENRES.items():
        if re.search(rf"\b{re.escape(token)}\b", text):
            intent.genre = canonical
            break

    decade = _DECADE_RE.search(text)
    if decade:
        start = int(decade.group(1) + decade.group(2))
        intent.year_min = start
        intent.year_max = start + 9
    else:
        years = [int(y.group(0)) for y in _YEARS_RE.finditer(text)]
        if years:
            intent.year_min = min(years)
            intent.year_max = max(years)

    if not intent.target and not intent.genre and not intent.query:
        intent.kind = "request" if is_request else "search"
        intent.query = text
    elif intent.kind == "search" and is_request:
        intent.kind = "request"
    return intent


def show_themes(name: str) -> list[str]:
    """Knowledge-base lookup for a TV show / film name (case-insensitive)."""
    return SHOW_THEMES.get(_normalize(name), [])


def _llm_extract(message: str, settings: Settings) -> dict[str, Any] | None:
    """Ask the configured OpenAI-compatible model for a discovery intent.

    Returns None on any failure (no key, network error, non-JSON reply) —
    the caller falls back to heuristics.
    """
    if not settings.chat_api_key:
        return None
    system = (
        "You extract book-discovery intents from the user's message. "
        "For 'similar to X' requests, infer 2-4 short theme/genre phrases for X. "
        'Reply with ONLY JSON: {"themes": [...], "genre": string|null, '
        '"year_min": int|null, "year_max": int|null, "title": string|null, '
        '"author": string|null}.'
    )
    try:
        resp = httpx.post(
            f"{settings.chat_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.chat_api_key}"},
            json={
                "model": settings.chat_model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": message},
                ],
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return None
        return payload
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        return None


def _build_reply(intent: ChatIntent, count: int) -> str:
    if count == 0:
        themes = ", ".join(intent.themes[:3]) if intent.themes else ""
        suffix = f" ({themes})" if themes else ""
        return (
            f"I couldn't find books matching that{suffix}. Try adding a genre, author, or decade."
        )
    if intent.kind == "similar":
        source = intent.target.title() if intent.target else "that"
        themes = ", ".join(intent.themes[:3]) if intent.themes else "similar themes"
        return f"**{source}** leans into {themes}. Here are books with similar themes:"
    if intent.kind == "author":
        return f"Books by **{intent.query.title()}**:"
    if intent.genre:
        decade = ""
        if intent.year_min is not None:
            decade = f" from the {intent.year_min // 10}0s"
        return f"**{intent.genre.title()}**{decade}:"
    return "Here's what I found:"


def handle_message(session: Session, message: str) -> dict[str, Any]:
    """The chat endpoint: intent → themes → discovery search → suggestions."""
    settings = Settings()
    intent = parse_intent(message)
    llm = _llm_extract(message, settings)
    if llm:
        themes = [str(t) for t in (llm.get("themes") or []) if t]
        if themes:
            intent.themes = themes
        if llm.get("genre"):
            intent.genre = str(llm["genre"])
        if llm.get("author"):
            intent.kind = "author"
            intent.query = str(llm["author"])
        if llm.get("title"):
            intent.query = str(llm["title"])
        intent.year_min = llm.get("year_min") or intent.year_min
        intent.year_max = llm.get("year_max") or intent.year_max

    limit = 5
    works = []
    if intent.kind == "author" and intent.query:
        works = search_works(session, q=f"author:{intent.query}", limit=limit)
    elif intent.themes:
        works = search_works(session, q=" ".join(intent.themes), limit=limit)
    elif intent.genre:
        works = search_works(
            session,
            genre=intent.genre,
            year_min=intent.year_min,
            year_max=intent.year_max,
            limit=limit,
        )
    elif intent.query:
        works = search_works(session, q=intent.query, limit=limit)

    suggestions = [
        {
            "title": work.title,
            "author": work.author,
            "year": work.year,
            "source": work.source,
        }
        for work in works[:limit]
    ]
    return {
        "reply": _build_reply(intent, len(suggestions)),
        "intent": intent.kind,
        "suggestions": suggestions,
    }
