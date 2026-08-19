"""Notifications via Apprise (plan Task 1.13).

One library, 80+ services (Telegram, ntfy, Discord, Pushover, email…).
Configured through LIBARR_APPRISE_URLS (comma-separated Apprise URLs).
"""

from __future__ import annotations

import apprise

from libarr.config import Settings


def configured() -> bool:
    return bool(Settings().apprise_urls)


def notify(title: str, body: str) -> bool:
    """Send a notification to every configured service. False when unconfigured."""
    urls = Settings().apprise_urls
    if not urls:
        return False
    notifier = apprise.Apprise()
    for url in (u.strip() for u in urls.split(",") if u.strip()):
        notifier.add(url)
    return bool(notifier.notify(body=body, title=title))
