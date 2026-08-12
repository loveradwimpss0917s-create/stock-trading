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
        return_value=httpx.Response(200, json={"data": [{"Code": "72030"}]})
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
            httpx.Response(200, json={"data": [{"Code": "10000"}], "pagination_key": "page2"}),
            httpx.Response(200, json={"data": [{"Code": "20000"}]}),
        ]
    )
    client = JQuantsClient(api_key="test-key")
    result = client.fetch_equities_master()
    client.close()

    assert result == [{"Code": "10000"}, {"Code": "20000"}]


@respx.mock
def test_fetch_daily_quotes_pads_4_digit_code_to_5():
    route = respx.get(f"{BASE_URL}/equities/bars/daily").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = JQuantsClient(api_key="test-key")
    client.fetch_daily_quotes("7203", "2026-01-01", "2026-01-31")
    client.close()

    sent_params = dict(route.calls[0].request.url.params)
    assert sent_params["code"] == "72030"


@respx.mock
def test_fetch_daily_quotes_clamps_to_plan_coverage_on_400():
    # Live-confirmed 2026-08-12: requesting a range wider than the plan's
    # rolling window returns 400 with a message naming the actual covered
    # range. fetch_daily_quotes should parse it and retry clamped, instead
    # of surfacing the error to the caller.
    route = respx.get(f"{BASE_URL}/equities/bars/daily").mock(
        side_effect=[
            httpx.Response(
                400,
                json={
                    "message": "Your subscription covers the following dates: "
                    "2024-05-20 ~ 2026-05-20. If you want more data, please "
                    "check other plans:https://jpx-jquants.com/#dataset"
                },
            ),
            httpx.Response(200, json={"data": [{"Code": "72030", "Date": "2026-05-20"}]}),
        ]
    )
    client = JQuantsClient(api_key="test-key")
    import pipeline_py.ingest.common as common_mod

    original_sleep = common_mod.time.sleep
    common_mod.time.sleep = lambda seconds: None
    try:
        result = client.fetch_daily_quotes("72030", "2024-08-12", "2026-08-12")
    finally:
        common_mod.time.sleep = original_sleep
        client.close()

    assert result == [{"Code": "72030", "Date": "2026-05-20"}]
    retried_params = dict(route.calls[1].request.url.params)
    assert retried_params["from"] == "2024-08-12"  # requested start was within range
    assert retried_params["to"] == "2026-05-20"  # end clamped to plan coverage


@respx.mock
def test_retries_on_429_then_succeeds():
    respx.get(f"{BASE_URL}/equities/master").mock(
        side_effect=[
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json={"data": [{"Code": "72030"}]}),
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


def test_normalize_security_maps_live_confirmed_fields_and_pads_code():
    # Field names confirmed 2026-08-12 against a live Free-plan account —
    # short abbreviated names (CoName/Mkt/S17/S33/ScaleCat), not the
    # CompanyName/MarketCode-style names the design blueprint assumed.
    raw = {
        "Code": "7203",
        "CoName": "トヨタ自動車",
        "CoNameEn": "TOYOTA MOTOR CORPORATION",
        "Mkt": "0111",
        "S17": "1",
        "S33": "0050",
        "ScaleCat": "TOPIX Small 1",
    }
    row = normalize_security(raw)
    assert row["code"] == "72030"
    assert row["ticker4"] == "7203"
    assert row["name_ja"] == "トヨタ自動車"
    assert row["name_en"] == "TOYOTA MOTOR CORPORATION"
    assert row["market_code"] == "0111"
    assert row["sector17"] == "1"
    assert row["sector33"] == "0050"
    assert row["scale_category"] == "TOPIX Small 1"


def test_normalize_daily_quote_maps_live_confirmed_fields_and_stamps_known_from():
    # Field names confirmed 2026-08-12 against a live Free-plan account —
    # abbreviated O/H/L/C/Vo/Va, not the Open/High/Low/Close/Volume names
    # the design blueprint assumed.
    raw = {
        "Code": "13010",
        "Date": "2024-08-13",
        "O": 3740.0,
        "H": 3800.0,
        "L": 3740.0,
        "C": 3795.0,
        "Vo": 22300.0,
        "Va": 84170500.0,
        "AdjFactor": 1.0,
        "AdjC": 3795.0,
    }
    row = normalize_daily_quote(raw)
    assert row["code"] == "13010"
    assert row["date"] == "2024-08-13"
    assert row["open"] == 3740.0
    assert row["high"] == 3800.0
    assert row["low"] == 3740.0
    assert row["close"] == 3795.0
    assert row["volume"] == 22300.0
    assert row["turnover_value"] == 84170500.0
    assert row["adj_factor"] == 1.0
    assert row["adj_close"] == 3795.0
    assert row["known_from"]  # stamped, non-empty


def test_normalize_daily_quote_preserves_a_real_zero_volume():
    # Vo=0 is a legitimate "no trades that day" value, not a missing field —
    # must not be treated the same as absent.
    raw = {"Code": "13010", "Date": "2024-08-13", "O": 100, "H": 100, "L": 100, "C": 100, "Vo": 0}
    row = normalize_daily_quote(raw)
    assert row["volume"] == 0
