import httpx
import respx

from pipeline_py.ingest.jquants import (
    BASE_URL,
    JQuantsClient,
    normalize_daily_quote,
    normalize_security,
)


@respx.mock
def test_fetch_equities_master_sends_api_key_header():
    route = respx.get(f"{BASE_URL}/equities/master").mock(
        return_value=httpx.Response(200, json={"equities": [{"Code": "72030"}]})
    )
    client = JQuantsClient(api_key="test-key")
    result = client.fetch_equities_master()
    client.close()

    assert result == [{"Code": "72030"}]
    sent_headers = route.calls[0].request.headers
    assert sent_headers["x-api-key"] == "test-key"


@respx.mock
def test_fetch_equities_master_follows_pagination_key():
    respx.get(f"{BASE_URL}/equities/master").mock(
        side_effect=[
            httpx.Response(200, json={"equities": [{"Code": "10000"}], "pagination_key": "page2"}),
            httpx.Response(200, json={"equities": [{"Code": "20000"}]}),
        ]
    )
    client = JQuantsClient(api_key="test-key")
    result = client.fetch_equities_master()
    client.close()

    assert result == [{"Code": "10000"}, {"Code": "20000"}]


@respx.mock
def test_fetch_daily_quotes_pads_4_digit_code_to_5():
    route = respx.get(f"{BASE_URL}/equities/bars/daily").mock(
        return_value=httpx.Response(200, json={"daily_quotes": []})
    )
    client = JQuantsClient(api_key="test-key")
    client.fetch_daily_quotes("7203", "2026-01-01", "2026-01-31")
    client.close()

    sent_params = dict(route.calls[0].request.url.params)
    assert sent_params["code"] == "72030"


@respx.mock
def test_retries_on_429_then_succeeds():
    respx.get(f"{BASE_URL}/equities/master").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json={"equities": [{"Code": "72030"}]}),
        ]
    )
    client = JQuantsClient(api_key="test-key")
    # Patch the client's sleep so the exponential backoff doesn't actually wait.
    client._limiter._sleep = lambda seconds: None  # rate limiter, not used here
    import pipeline_py.ingest.common as common_mod

    original_sleep = common_mod.time.sleep
    common_mod.time.sleep = lambda seconds: None
    try:
        result = client.fetch_equities_master()
    finally:
        common_mod.time.sleep = original_sleep
        client.close()

    assert result == [{"Code": "72030"}]


def test_normalize_security_maps_camelcase_fields_and_pads_code():
    raw = {"Code": "7203", "CompanyName": "トヨタ自動車", "MarketCode": "0111"}
    row = normalize_security(raw)
    assert row["code"] == "72030"
    assert row["ticker4"] == "7203"
    assert row["name_ja"] == "トヨタ自動車"
    assert row["market_code"] == "0111"


def test_normalize_daily_quote_maps_fields_and_stamps_known_from():
    raw = {"Code": "72030", "Date": "2026-01-05", "Open": 100, "Close": 105}
    row = normalize_daily_quote(raw)
    assert row["code"] == "72030"
    assert row["date"] == "2026-01-05"
    assert row["open"] == 100
    assert row["close"] == 105
    assert row["known_from"]  # stamped, non-empty
