"""
Optional alert notification channels (Telegram + email).

Both channels are strictly optional and gated on environment variables —
the app runs identically with none of them set, and `notify()` then just
logs the message. No new dependencies: Telegram uses `requests` (already a
dependency), email uses the stdlib `smtplib`/`email` modules.

`notify()` never raises: a failing notification must not break the alert
(or background job) that triggered it — the error is logged and the caller
learns which channels actually delivered.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import requests

from .config import settings

logger = logging.getLogger("neural_market.notifications")


def _telegram_configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_to)


def _send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    resp = requests.post(url, json={"chat_id": settings.telegram_chat_id, "text": text[:4000]}, timeout=10)
    resp.raise_for_status()


def _send_email(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user or "Neural Market"
    msg["To"] = settings.smtp_to
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)


def configured_channels() -> list[str]:
    """Which channels would actually receive a notification right now."""
    channels = []
    if _telegram_configured():
        channels.append("telegram")
    if _smtp_configured():
        channels.append("email")
    return channels


def notify(subject: str, body: str) -> list[str]:
    """Send to every configured channel. Returns the list of channels that
    delivered; empty if none were configured or all failed. Never raises."""
    delivered: list[str] = []
    full_text = f"{subject}\n\n{body}" if subject else body

    if _telegram_configured():
        try:
            _send_telegram(full_text)
            delivered.append("telegram")
        except Exception as exc:
            logger.warning("telegram notification failed: %s", exc)

    if _smtp_configured():
        try:
            _send_email(subject, body)
            delivered.append("email")
        except Exception as exc:
            logger.warning("email notification failed: %s", exc)

    if not delivered:
        logger.info("no notification channels configured; alert message: %s", full_text)
    return delivered