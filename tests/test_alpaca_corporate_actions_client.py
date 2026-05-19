import pytest
import requests

from src.ingestion.alpaca_client import AlpacaConfig
from src.ingestion.alpaca_corporate_actions_client import (
    AlpacaCorporateActionsClient,
    CorporateActionRecord,
)


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        if not self.responses:
            raise AssertionError("Unexpected extra HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_client(responses):
    cfg = AlpacaConfig(
        api_key_id="test-key",
        api_secret_key="test-secret",
        data_base_url="https://data.alpaca.markets",
        max_retries=1,
        timeout_s=5,
    )
    return AlpacaCorporateActionsClient(cfg, session=FakeSession(responses))


def dividend_payload(action_type="cash_dividend", symbol="AAPL", action_id="ca-1"):
    return {
        "id": action_id,
        "symbol": symbol,
        "type": action_type,
        "process_date": "2025-01-15",
        "ex_date": "2025-01-10",
    }


def test_successful_corporate_actions_request_returns_records():
    payload = dividend_payload(action_type="cash_dividend")
    client = make_client([FakeResponse({"corporate_actions": [payload]})])

    records = client.fetch_corporate_actions(
        symbols=["AAPL"],
        start="2025-01-01",
        end="2025-01-31",
        types=["cash_dividend"],
    )

    assert records == [CorporateActionRecord.from_payload(payload)]
    assert records[0].as_dict() == payload
    assert client.session.calls[0]["url"] == "https://data.alpaca.markets/v1/corporate-actions"


def test_cash_dividend_request_sends_cash_dividend_type():
    client = make_client([FakeResponse({"corporate_actions": []})])

    records = client.fetch_corporate_actions(
        symbols="AAPL",
        start="2025-01-01",
        end="2025-01-31",
        types="cash_dividend",
    )

    assert records == []
    params = client.session.calls[0]["params"]
    assert params["symbols"] == "AAPL"
    assert params["types"] == "cash_dividend"


def test_stock_dividend_request_sends_stock_dividend_type():
    client = make_client([FakeResponse({"corporate_actions": []})])

    client.fetch_corporate_actions(
        symbols=["AAPL"],
        start="2025-01-01",
        end="2025-01-31",
        types=["stock_dividend"],
    )

    assert client.session.calls[0]["params"]["types"] == "stock_dividend"


def test_combined_dividend_request_sends_both_types():
    client = make_client([FakeResponse({"corporate_actions": []})])

    client.fetch_dividends(
        symbols=["AAPL", "MSFT"],
        start="2025-01-01",
        end="2025-01-31",
        limit=500,
        sort="desc",
    )

    params = client.session.calls[0]["params"]
    assert params["symbols"] == "AAPL,MSFT"
    assert params["types"] == "cash_dividend,stock_dividend"
    assert params["limit"] == 500
    assert params["sort"] == "desc"


def test_empty_api_response_returns_empty_list():
    client = make_client([FakeResponse({"corporate_actions": []})])

    records = client.fetch_dividends(symbols=["AAPL"], start="2025-01-01", end="2025-01-31")

    assert records == []


def test_pagination_collects_multiple_pages():
    client = make_client(
        [
            FakeResponse(
                {
                    "corporate_actions": [
                        dividend_payload(action_type="cash_dividend", action_id="ca-1")
                    ],
                    "next_page_token": "next-1",
                }
            ),
            FakeResponse(
                {
                    "corporate_actions": [
                        dividend_payload(action_type="stock_dividend", action_id="ca-2")
                    ]
                }
            ),
        ]
    )

    records = client.fetch_dividends(symbols=["AAPL"], start="2025-01-01", end="2025-12-31")

    assert [record.id for record in records] == ["ca-1", "ca-2"]
    assert len(client.session.calls) == 2
    assert "page_token" not in client.session.calls[0]["params"]
    assert client.session.calls[1]["params"]["page_token"] == "next-1"


def test_api_client_error_is_wrapped():
    client = make_client([FakeResponse({"message": "bad request"}, status_code=400, text="bad request")])

    with pytest.raises(RuntimeError, match="Alpaca corporate-actions request failed"):
        client.fetch_dividends(symbols=["AAPL"], start="2025-01-01", end="2025-01-31")


def test_unsupported_action_type_validation():
    client = make_client([])

    with pytest.raises(ValueError, match="Unsupported corporate action type"):
        client.fetch_corporate_actions(
            symbols=["AAPL"],
            start="2025-01-01",
            end="2025-01-31",
            types=["forward_split"],
        )

    assert client.session.calls == []


@pytest.mark.parametrize("limit", [0, 1001])
def test_limit_validation(limit):
    client = make_client([])

    with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
        client.fetch_dividends(symbols=["AAPL"], start="2025-01-01", end="2025-01-31", limit=limit)


def test_sort_validation():
    client = make_client([])

    with pytest.raises(ValueError, match="sort must be either"):
        client.fetch_dividends(symbols=["AAPL"], start="2025-01-01", end="2025-01-31", sort="newest")
