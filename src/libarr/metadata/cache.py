"""Resilient metadata cache (plan §2.3 — the anti-Readarr design).

Every provider call goes through cached_fetch: fresh responses are served
from the local metadata_cache table within a TTL, and if the provider fails
after the TTL, the last-known payload is served (stale-while-error). This is
what keeps the app alive when a metadata source dies — the exact failure mode
that killed Readarr.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy.orm import Session

from libarr.models import MetadataCache

DEFAULT_TTL = timedelta(days=30)


def cached_fetch(
    session: Session,
    provider: str,
    kind: str,
    key: str,
    fetcher: Callable[[], dict[str, Any]],
    ttl: timedelta = DEFAULT_TTL,
) -> dict[str, Any]:
    """Return a provider payload, serving the local cache when possible."""
    row = session.get(MetadataCache, (provider, kind, key))
    # SQLite returns naive datetimes — keep everything naive-UTC for comparison.
    now = datetime.now(UTC).replace(tzinfo=None)

    if row is not None and now - row.fetched_at < ttl:
        return cast(dict[str, Any], json.loads(row.payload_json))

    try:
        payload = fetcher()
    except Exception:
        if row is not None:
            return cast(dict[str, Any], json.loads(row.payload_json))  # stale-while-error
        raise

    serialized = json.dumps(payload, ensure_ascii=False)
    if row is not None:
        row.payload_json = serialized
        row.fetched_at = now
    else:
        session.add(
            MetadataCache(
                provider=provider, kind=kind, key=key,
                payload_json=serialized, fetched_at=now,
            )
        )
    session.commit()
    return payload
