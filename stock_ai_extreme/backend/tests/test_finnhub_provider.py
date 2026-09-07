from datetime import date
from unittest.mock import Mock, patch

import pytest
import requests

from app.providers.base import DataStatus, ProviderError
from app.providers.finnhub_provider import FinnhubProvider


@pytest.mark.asyncio
async def test_no_api_key_raises_without_making_a_request():
    provider = FinnhubProvider(api_key=None)
    assert provider.is_configured() is False
    with patch("app.providers.finnhub_provider.requests.get") as mock_get:
        with pytest.raises(ProviderError):
            await provider.get_quote("AAPL")
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_successful_quote_is_parsed_correctly():
    provider = FinnhubProvider(api_key="dummy-key")
    fake_response = Mock()
    fake_response.json.return_value = {"c": 210.5, "pc": 208.0, "dp": 1.2}
    fake_response.raise_for_status = Mock()
    with patch("app.providers.finnhub_provider.requests.get", return_value=fake_response) as mock_get:
        quote = await provider.get_quote("aapl")
    assert quote.ticker == "AAPL"
    assert quote.price == 210.5
    assert quote.previous_close == 208.0
    assert quote.status == DataStatus.LIVE
    mock_get.assert_called_once()
    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["symbol"] == "AAPL"
    assert called_params["token"] == "dummy-key"


@pytest.mark.asyncio
async def test_network_failure_raises_provider_error():
    provider = FinnhubProvider(api_key="dummy-key")
    with patch("app.providers.finnhub_provider.requests.get", side_effect=requests.ConnectionError("down")):
        with pytest.raises(ProviderError):
            await provider.get_quote("AAPL")


@pytest.mark.asyncio
async def test_zero_price_treated_as_unsupported_symbol():
    provider = FinnhubProvider(api_key="dummy-key")
    fake_response = Mock()
    fake_response.json.return_value = {"c": 0, "pc": 0, "dp": 0}
    fake_response.raise_for_status = Mock()
    with patch("app.providers.finnhub_provider.requests.get", return_value=fake_response):
        with pytest.raises(ProviderError):
            await provider.get_quote("UNKNOWNSYMBOL")


@pytest.mark.asyncio
async def test_get_history_always_unsupported():
    provider = FinnhubProvider(api_key="dummy-key")
    with pytest.raises(ProviderError):
        await provider.get_history("AAPL", date.today(), date.today())
