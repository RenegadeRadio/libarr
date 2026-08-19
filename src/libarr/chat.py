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

# Curated "what is this show about" knowledge base for TV series (and a few
# landmark films). Themes are chosen to map onto Open Library subject search.
SHOW_THEMES: dict[str, list[str]] = {
    # --- conspiracy / espionage / intelligence ------------------------------
    "rubicon": ["conspiracy", "espionage", "intelligence services", "paranoia"],
    "rabbithole": ["conspiracy", "corporate espionage", "paranoia", "thrillers"],
    "the americans": ["espionage", "cold war", "spies"],
    "homeland": ["espionage", "counterterrorism", "paranoia"],
    "the night manager": ["espionage", "arms trade", "thrillers"],
    "slow horses": ["espionage", "intelligence services", "misfits"],
    "spooks": ["espionage", "intelligence services", "counterterrorism"],
    "mi-5": ["espionage", "intelligence services", "counterterrorism"],
    "24": ["counterterrorism", "action", "race against time"],
    "the blacklist": ["crime", "espionage", "master criminal"],
    "alias": ["espionage", "secret agents", "action"],
    "the x-files": ["conspiracy", "paranormal", "fbi", "mystery"],
    "tinker tailor soldier spy": ["espionage", "cold war", "spies", "mole hunting"],
    "le carre": ["espionage", "cold war", "spies", "moral ambiguity"],
    # --- science fiction ------------------------------------------------------
    "the expanse": ["space opera", "political intrigue", "hard science fiction"],
    "severance": ["dystopia", "corporate satire", "identity", "science fiction"],
    "dark": ["time travel", "mystery", "small town secrets", "science fiction"],
    "black mirror": ["dystopia", "technology", "speculative fiction"],
    "mr robot": ["hacking", "paranoia", "conspiracy", "technology"],
    "westworld": ["artificial intelligence", "dystopia", "philosophy"],
    "altered carbon": ["cyberpunk", "immortality", "dystopia", "science fiction"],
    "battlestar galactica": ["space opera", "survival", "artificial intelligence", "war"],
    "star trek": ["space exploration", "utopia", "aliens", "science fiction"],
    "firefly": ["space western", "frontier", "outlaws", "science fiction"],
    "foundation": ["space opera", "empire", "science fiction", "mathematics"],
    "the mandalorian": ["space western", "bounty hunters", "found family"],
    "andor": ["rebellion", "empire", "espionage", "space opera"],
    "silo": ["dystopia", "underground", "mystery", "post-apocalyptic"],
    "fallout": ["post-apocalyptic", "survival", "dystopia", "science fiction"],
    "the last of us": ["post-apocalyptic", "survival", "fatherhood", "horror"],
    "devs": ["quantum computing", "determinism", "technology", "mystery"],
    "counterpart": ["parallel worlds", "espionage", "identity", "science fiction"],
    "12 monkeys": ["time travel", "plague", "paradox", "science fiction"],
    "the man in the high castle": ["alternate history", "dystopia", "resistance"],
    "orphan black": ["clones", "identity", "biotech", "mystery"],
    "fringe": ["paranormal", "parallel worlds", "fbi", "science fiction"],
    "the 100": ["post-apocalyptic", "survival", "young adults", "science fiction"],
    "lost": ["mystery", "island", "survival", "science fiction"],
    "stranger things": ["1980s", "supernatural", "small town", "nostalgia"],
    "outer range": ["mystery", "western", "time", "supernatural"],
    "the orville": ["space comedy", "space exploration", "science fiction"],
    "doctor who": ["time travel", "adventure", "aliens", "science fiction"],
    # --- fantasy ----------------------------------------------------------------
    "game of thrones": ["epic fantasy", "political intrigue", "power", "medieval"],
    "house of the dragon": ["epic fantasy", "political intrigue", "dragons"],
    "the witcher": ["dark fantasy", "monster hunting", "magic", "destiny"],
    "the wheel of time": ["epic fantasy", "chosen one", "magic", "prophecy"],
    "the rings of power": ["epic fantasy", "middle earth", "ancient history"],
    "the sandman": ["dreams", "mythology", "dark fantasy", "morality"],
    "his dark materials": ["parallel worlds", "coming of age", "philosophy"],
    "shadow and bone": ["magic", "war", "chosen one", "fantasy"],
    "the magicians": ["magic school", "dark fantasy", "coming of age"],
    "american gods": ["mythology", "american road trip", "old gods vs new"],
    "supernatural": ["demons", "hunting", "brothers", "supernatural"],
    "buffy": ["vampires", "demon hunting", "high school", "chosen one"],
    "merlin": ["arthurian", "magic", "court intrigue", "fantasy"],
    "outlander": ["time travel", "highlands", "romance", "historical"],
    "the shannara chronicles": ["epic fantasy", "magic", "quest"],
    "kaos": ["greek mythology", "gods", "dark comedy"],
    "percy jackson": ["greek mythology", "young adults", "quest"],
    # --- crime / detective / noir -----------------------------------------------
    "the wire": ["crime", "police", "urban drama", "institutional failure"],
    "true detective": ["crime", "detective", "gothic", "philosophy"],
    "fargo": ["crime", "dark comedy", "midwest noir"],
    "breaking bad": ["crime", "moral descent", "chemistry", "family"],
    "better call saul": ["legal drama", "crime", "moral decline", "prequel"],
    "the sopranos": ["mob", "family", "psychology", "crime"],
    "the shield": ["police corruption", "crime", "moral ambiguity"],
    "sherlock": ["detective", "mystery", "london", "brilliant mind"],
    "luther": ["detective", "crime", "dark", "obsession"],
    "mindhunter": ["serial killers", "fbi", "criminal psychology", "1970s"],
    "ozark": ["crime", "money laundering", "family", "rural noir"],
    "narcos": ["drug cartels", "colombia", "crime", "true story"],
    "peaky blinders": ["gangsters", "1920s", "birmingham", "crime"],
    "dexter": ["serial killer", "vigilante", "crime", "double life"],
    "the killing": ["murder investigation", "detective", "rainy noir"],
    "broadchurch": ["murder mystery", "small town", "detective"],
    "mare of easttown": ["murder mystery", "small town", "detective"],
    "bosch": ["detective", "los angeles", "police procedural"],
    "lincoln lawyer": ["legal drama", "courtroom", "crime"],
    "columbo": ["detective", "whodunit", "classic mystery"],
    "poirot": ["detective", "whodunit", "agatha christie"],
    "the night of": ["legal drama", "murder trial", "crime"],
    "happy valley": ["detective", "crime", "yorkshire", "gritty"],
    "only murders in the building": ["murder mystery", "true crime podcast", "comedy"],
    "twin peaks": ["mystery", "surrealism", "small town secrets", "fbi"],
    # --- political / legal ---------------------------------------------------------
    "house of cards": ["political intrigue", "power", "ambition"],
    "the west wing": ["politics", "white house", "idealism", "drama"],
    "the newsroom": ["journalism", "news media", "idealism"],
    "scandal": ["politics", "crisis management", "drama"],
    "designated survivor": ["politics", "conspiracy", "succession"],
    "suits": ["legal drama", "corporate law", "genius imposter"],
    "the good wife": ["legal drama", "politics", "scandal"],
    "law & order": ["legal drama", "police procedural", "courtroom"],
    # --- historical / war / period ---------------------------------------------------
    "band of brothers": ["world war ii", "paratroopers", "brotherhood", "war"],
    "the pacific": ["world war ii", "marines", "war"],
    "chernobyl": ["disaster", "nuclear", "true story", "cover-up"],
    "vikings": ["norse", "raids", "sagas", "historical"],
    "the last kingdom": ["anglo-saxon", "viking invasions", "historical"],
    "rome": ["ancient rome", "politics", "legions", "historical"],
    "the crown": ["royal family", "british history", "power", "drama"],
    "mad men": ["1960s", "advertising", "midlife crisis", "period drama"],
    "boardwalk empire": ["prohibition", "gangsters", "1920s", "atlantic city"],
    "deadwood": ["western", "frontier town", "profanity", "american history"],
    "downton abbey": ["upstairs downstairs", "edwardian", "family drama", "period"],
    "bridgerton": ["regency", "romance", "high society", "period"],
    "black sails": ["pirates", "treasure island", "nautical", "prequel"],
    "the terror": ["arctic expedition", "horror", "historical", "survival"],
    "turn": ["american revolution", "spies", "historical"],
    "spartacus": ["ancient rome", "gladiators", "slave rebellion"],
    "the tudors": ["henry viii", "court intrigue", "british history"],
    # --- horror / supernatural --------------------------------------------------------
    "american horror story": ["horror", "anthology", "supernatural"],
    "the haunting of hill house": ["ghosts", "family trauma", "gothic horror"],
    "the walking dead": ["zombies", "survival", "post-apocalyptic", "group dynamics"],
    "yellowjackets": ["survival", "mystery", "1990s", "psychological"],
    "hannibal": ["serial killer", "psychology", "dark", "crime"],
    "the strain": ["vampires", "plague", "horror"],
    "from": ["mystery", "trapped town", "horror", "monsters"],
    "channel zero": ["creepypasta", "horror", "anthology"],
    # --- comedy --------------------------------------------------------------------------
    "the office": ["workplace comedy", "mockumentary", "office life"],
    "parks and recreation": ["workplace comedy", "local government", "mockumentary"],
    "community": ["community college", "meta comedy", "study group"],
    "arrested development": ["dysfunctional family", "satire", "running gags"],
    "seinfeld": ["standup comedy", "everyday life", "observational"],
    "curb your enthusiasm": ["improvised comedy", "social faux pas"],
    "30 rock": ["showbiz satire", "sketch comedy", "workplace"],
    "brooklyn nine-nine": ["police comedy", "workplace", "ensemble"],
    "ted lasso": ["football", "optimism", "found family", "comedy"],
    "schitt's creek": ["fish out of water", "family", "small town", "comedy"],
    "fleabag": ["dark comedy", "grief", "fourth wall", "london"],
    "the good place": ["afterlife", "philosophy", "moral ethics", "comedy"],
    "it's always sunny": ["dark comedy", "dysfunctional friends", "philadelphia"],
    # --- medical ----------------------------------------------------------------------------
    "house": ["medical drama", "diagnosis", "grumpy genius"],
    "grey's anatomy": ["medical drama", "surgical interns", "romance"],
    "scrubs": ["medical comedy", "interns", "daydreams"],
    "the good doctor": ["medical drama", "autism", "genius surgeon"],
    # --- animation / other -------------------------------------------------------------------
    "attack on titan": ["dark fantasy", "giants", "war", "anime"],
    "cowboy bebop": ["space western", "bounty hunters", "jazz", "anime"],
    "avatar the last airbender": ["elemental magic", "war", "coming of age", "anime"],
    "arcane": ["steampunk", "sisters", "class conflict", "animation"],
    "one piece": ["pirates", "adventure", "found family", "anime"],
    "the simpsons": ["family sitcom", "satire", "springfield"],
    "rick and morty": ["science fiction", "multiverse", "dark comedy", "animation"],
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
        # Subject search is far more reliable than keyword phrases for theme
        # discovery (OL keyword search degrades on multi-term phrases).
        works = []
        seen: set[tuple[str, str]] = set()
        for theme in intent.themes[:2]:
            for work in search_works(session, genre=theme, limit=limit):
                key = (work.title, work.author or "")
                if key not in seen:
                    seen.add(key)
                    works.append(work)
            if len(works) >= limit:
                break
        if not works:  # subject search came up empty → keyword fallback
            query = " ".join(intent.themes[:3])
            works = search_works(session, q=query, limit=limit)
            if not works and len(intent.themes) > 1:
                works = search_works(session, q=intent.themes[0], limit=limit)
        works = works[:limit]
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
