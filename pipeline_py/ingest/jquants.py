"""J-Quants API V2 client (retail product, host api.jquants.com).

Free plan: 5 requests/min, auth via `x-api-key` header. V1's token flow
(refresh token -> ID token -> `Authorization: Bearer`) was retired for V2 —
do not port that pattern from older articles/examples.

Do not confuse this with the separate corporate "J-Quants Pro" product
(host api.jquants-pro.com, underscore paths, `Authorization: Bearer`).
"""
from __future__ import annotations

import os
from typing import Any, Iterator, Optional

import httpx

from .common import TokenBucketRateLimiter, now_utc_iso, pad_security_code, retry_with_backoff

BASE_URL = "https://api.jquants.com/v2"
FREE_PLAN_RATE_LIMIT_PER_MIN = 5


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, httpx.TransportError)


class JQuantsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        rate_limit_per_min: int = FREE_PLAN_RATE_LIMIT_PER_MIN,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(base_url=base_url, timeout=30.0)
        self._limiter = TokenBucketRateLimiter(rate_limit_per_min, 60.0)

    @classmethod
    def from_env(cls) -> "JQuantsClient":
        return cls(api_key=os.environ["JQUANTS_API_KEY"])

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "JQuantsClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        def _do() -> dict[str, Any]:
            self._limiter.acquire()
            resp = self.client.get(path, params=params, headers={"x-api-key": self.api_key})
            resp.raise_for_status()
            return resp.json()

        return retry_with_backoff(_do, should_retry=_is_retryable)

    def _get_paginated(self, path: str, params: dict[str, Any], items_key: str) -> Iterator[dict[str, Any]]:
        query = dict(params)
        while True:
            page = self._get(path, query)
            yield from page.get(items_key, [])
            pagination_key = page.get("pagination_key")
            if not pagination_key:
                return
            query = dict(params)
            query["pagination_key"] = pagination_key

    def fetch_equities_master(self) -> list[dict[str, Any]]:
        return list(self._get_paginated("/equities/master", {}, "equities"))

    def fetch_daily_quotes(self, code: str, date_from: str, date_to: str) -> list[dict[str, Any]]:
        params = {"code": pad_security_code(code), "from": date_from, "to": date_to}
        return list(self._get_paginated("/equities/bars/daily", params, "daily_quotes"))

    def fetch_fins_summary(self, code: str) -> list[dict[str, Any]]:
        params = {"code": pad_security_code(code)}
        return list(self._get_paginated("/fins/summary", params, "summaries"))


def normalize_security(raw: dict[str, Any]) -> dict[str, Any]:
    code = pad_security_code(raw.get("Code") or raw.get("code") or "")
    return {
        "code": code,
        "ticker4": code[:4],
        "name_ja": raw.get("CompanyName") or raw.get("company_name"),
        "name_en": raw.get("CompanyNameEnglish") or raw.get("company_name_english"),
        "market_code": raw.get("MarketCode") or raw.get("market_code"),
        "sector17": raw.get("Sector17Code") or raw.get("sector17_code"),
        "sector33": raw.get("Sector33Code") or raw.get("sector33_code"),
        "scale_category": raw.get("ScaleCategory") or raw.get("scale_category"),
        "listed_date": raw.get("ListedDate") or raw.get("listed_date"),
        "delisted_date": raw.get("DelistedDate") or raw.get("delisted_date"),
    }


def normalize_daily_quote(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": pad_security_code(raw.get("Code") or raw.get("code") or ""),
        "date": raw.get("Date") or raw.get("date"),
        "open": raw.get("Open"),
        "high": raw.get("High"),
        "low": raw.get("Low"),
        "close": raw.get("Close"),
        "volume": raw.get("Volume"),
        "turnover_value": raw.get("TurnoverValue"),
        "known_from": now_utc_iso(),
    }
