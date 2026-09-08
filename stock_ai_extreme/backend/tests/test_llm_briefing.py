from unittest.mock import Mock, patch

import pytest
import requests

from app.llm_briefing import generate_briefing, is_configured


def test_not_configured_returns_unavailable_without_a_request():
    with patch("app.llm_briefing.requests.post") as mock_post:
        result = generate_briefing({"ticker": "AAPL"}, api_key=None)
    assert result["status"] == "UNAVAILABLE"
    mock_post.assert_not_called()


def test_is_configured():
    assert is_configured("sk-ant-real-key") is True
    assert is_configured(None) is False
    assert is_configured("") is False


def test_successful_response_is_parsed():
    fake_response = Mock()
    fake_response.raise_for_status = Mock()
    fake_response.json.return_value = {"content": [{"type": "text", "text": "AAPL closed flat with low volatility."}]}
    with patch("app.llm_briefing.requests.post", return_value=fake_response) as mock_post:
        result = generate_briefing({"ticker": "AAPL", "price": 190.0}, api_key="sk-ant-test")
    assert result["status"] == "OK"
    assert "AAPL" in result["text"]
    # confirm the real data was actually sent to the model, not a placeholder
    sent_payload = mock_post.call_args.kwargs["json"]
    assert "190.0" in sent_payload["messages"][0]["content"]
    assert mock_post.call_args.kwargs["headers"]["x-api-key"] == "sk-ant-test"


def test_network_failure_returns_error_status():
    with patch("app.llm_briefing.requests.post", side_effect=requests.ConnectionError("no route")):
        result = generate_briefing({"ticker": "AAPL"}, api_key="sk-ant-test")
    assert result["status"] == "ERROR"
    assert result["text"] is None


def test_empty_content_returns_error_status():
    fake_response = Mock()
    fake_response.raise_for_status = Mock()
    fake_response.json.return_value = {"content": []}
    with patch("app.llm_briefing.requests.post", return_value=fake_response):
        result = generate_briefing({"ticker": "AAPL"}, api_key="sk-ant-test")
    assert result["status"] == "ERROR"


def test_prompt_instructs_the_model_not_to_invent_numbers():
    from app.llm_briefing import SYSTEM_PROMPT
    assert "invent" in SYSTEM_PROMPT.lower()
    assert "advice" in SYSTEM_PROMPT.lower()
