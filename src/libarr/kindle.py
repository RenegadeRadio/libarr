"""Send-to-Kindle (Phase 3): email a library file to a @kindle.com address.

Uses the standard library (smtplib + email) with STARTTLS. Configuration via
environment: LIBARR_SMTP_HOST / _PORT / _USERNAME / _PASSWORD / _FROM.
"""

from __future__ import annotations

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from libarr.config import Settings


class KindleError(Exception):
    """Raised when the email cannot be prepared or sent."""


def send_to_kindle(settings: Settings, *, to: str, file_path: Path, title: str) -> None:
    if not settings.smtp_host:
        raise KindleError("SMTP is not configured (LIBARR_SMTP_HOST)")
    source = Path(file_path)
    if not source.is_file():
        raise KindleError(f"file not found: {source}")

    message = MIMEMultipart()
    message["Subject"] = f"Libarr: {title}"
    message["From"] = settings.smtp_from or settings.smtp_username
    message["To"] = to
    message.attach(MIMEText("Sent by Libarr — your self-hosted ebook automation.", "plain"))

    with open(source, "rb") as handle:
        attachment = MIMEApplication(handle.read(), _subtype="octet-stream")
    attachment.add_header("Content-Disposition", "attachment", filename=source.name)
    message.attach(attachment)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password or "")
        server.sendmail(settings.smtp_from or settings.smtp_username, [to], message.as_string())
