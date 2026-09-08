"""
Tests for the optional notification channels (Telegram + email).

All network calls are mocked — these tests verify wiring and error
isolation, not that Telegram/SMTP are reachable.
"""
import pytest
from unittest.mock import patch

from app import notifications
from app.notifications import configured_channels, notify


@pytest.fixture(autouse=True)
def _no_channels(monkeypatch):
    """Default: no channels configured, so tests are hermetic."""
    monkeypatch.setattr(notifications.settings, "telegram_bot_token", None)
    monkeypatch.setattr(notifications.settings, "telegram_chat_id", None)
    monkeypatch.setattr(notifications.settings, "smtp_host", None)
    monkeypatch.setattr(notifications.settings, "smtp_to", None)


def test_notify_with_no_channels_returns_empty():
    assert notify("subject", "body") == []
    assert configured_channels() == []


def test_telegram_channel_delivers(monkeypatch):
    monkeypatch.setattr(notifications.settings, "telegram_bot_token", "token")
    monkeypatch.setattr(notifications.settings, "telegram_chat_id", "123")
    with patch("app.notifications.requests.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        delivered = notify("Alert!", "AAPL above 200")
    assert delivered == ["telegram"]
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert "api.telegram.org" in url and "token" in url
    payload = mock_post.call_args[1]["json"]
    assert payload["chat_id"] == "123" and "AAPL above 200" in payload["text"]


def test_telegram_failure_is_swallowed_and_reported(monkeypatch):
    monkeypatch.setattr(notifications.settings, "telegram_bot_token", "token")
    monkeypatch.setattr(notifications.settings, "telegram_chat_id", "123")
    with patch("app.notifications.requests.post", side_effect=RuntimeError("network down")):
        delivered = notify("Alert!", "body")
    assert delivered == []  # failure must not raise, just not deliver


def test_email_channel_delivers(monkeypatch):
    monkeypatch.setattr(notifications.settings, "smtp_host", "smtp.test.com")
    monkeypatch.setattr(notifications.settings, "smtp_port", 587)
    monkeypatch.setattr(notifications.settings, "smtp_user", "u")
    monkeypatch.setattr(notifications.settings, "smtp_password", "p")
    monkeypatch.setattr(notifications.settings, "smtp_to", "a@b.com")
    with patch("app.notifications.smtplib.SMTP") as MockSMTP:
        instance = MockSMTP.return_value
        instance.__enter__.return_value = instance  # `with SMTP(...) as smtp:` binds to this same mock
        delivered = notify("Subject line", "Body text")
    assert delivered == ["email"]
    instance.starttls.assert_called_once()
    instance.login.assert_called_once_with("u", "p")
    instance.send_message.assert_called_once()
    msg = instance.send_message.call_args[0][0]
    assert msg["Subject"] == "Subject line" and msg["To"] == "a@b.com"


def test_email_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(notifications.settings, "smtp_host", "smtp.test.com")
    monkeypatch.setattr(notifications.settings, "smtp_to", "a@b.com")
    with patch("app.notifications.smtplib.SMTP", side_effect=RuntimeError("no route to host")):
        assert notify("s", "b") == []


def test_both_channels_deliver_when_configured(monkeypatch):
    monkeypatch.setattr(notifications.settings, "telegram_bot_token", "t")
    monkeypatch.setattr(notifications.settings, "telegram_chat_id", "1")
    monkeypatch.setattr(notifications.settings, "smtp_host", "smtp.test.com")
    monkeypatch.setattr(notifications.settings, "smtp_to", "a@b.com")
    with patch("app.notifications.requests.post") as mock_post, \
         patch("app.notifications.smtplib.SMTP") as MockSMTP:
        mock_post.return_value.raise_for_status.return_value = None
        MockSMTP.return_value.__enter__.return_value = MockSMTP.return_value
        delivered = notify("s", "b")
    assert sorted(delivered) == ["email", "telegram"]