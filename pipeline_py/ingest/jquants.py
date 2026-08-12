"""J-Quants API V2 client (retail product, host api.jquants.com).

Free plan: 5 requests/min, auth via `x-api-key` header. V1's token flow
(refresh token -> ID token -> `Authorization: Bearer`) was retired for V2 —
do not port that pattern from older articles/examples.

Do not confuse this with the separate corporate "J-Quants Pro" product
(host api.jquants-pro.com, underscore paths, `Authorization: Bearer`).
"""
from __future__ import annotations

import os
import re
from typing import Any, Iterator, Optional

import httpx

from .common import RetryExhausted, TokenBucketRateLimiter, now_utc_iso, pad_security_code, retry_with_backoff

BASE_URL = "https://api.jquants.com/v2"
FREE_PLAN_RATE_LIMIT_PER_MIN = 5

# Matches the body of the 400 /equities/bars/daily returns when the
# requested range exceeds what the plan's rolling window covers, e.g.:
#   "Your subscription covers the following dates: 2024-05-20 ~ 2026-05-20."
# Confirmed live 2026-08-12; ~12 weeks behind today, matching the design
# blueprint's stated Free-plan delay — but read from the API's own error
# rather than hardcoded, since the exact window isn't documented anywhere
# we could verify ahead of time.
_SUBSCRIPTION_RANGE_RE = re.compile(
    r"subscription covers the following dates: (\d{4}-\d{2}-\d{2}) ~ (\d{4}-\d{2}-\d{2})"
)


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
            if resp.status_code >= 400:
                # Non-retryable errors (4xx other than 429) never surface their
                # body otherwise — and that body is usually the only way to
                # know *which* param/format the API actually rejected.
                print(f"[jquants] {resp.status_code} from {path} params={params}: {resp.text[:1000]}", flush=True)
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
        return list(self._get_paginated("/equities/master", {}, "data"))

    def fetch_daily_quotes(self, code: str, date_from: str, date_to: str) -> list[dict[str, Any]]:
        params = {"code": pad_security_code(code), "from": date_from, "to": date_to}
        try:
            return list(self._get_paginated("/equities/bars/daily", params, "data"))
        except RetryExhausted as exc:
            cause = exc.__cause__
            if not isinstance(cause, httpx.HTTPStatusError) or cause.response.status_code != 400:
                raise
            match = _SUBSCRIPTION_RANGE_RE.search(cause.response.text)
            if not match:
                raise
            allowed_from, allowed_to = match.groups()
            clamped_from = max(date_from, allowed_from)
            clamped_to = min(date_to, allowed_to)
            print(
                f"[jquants] requested range {date_from}~{date_to} exceeds plan "
                f"coverage; retrying clamped to {clamped_from}~{clamped_to}",
                flush=True,
            )
            clamped_params = {"code": pad_security_code(code), "from": clamped_from, "to": clamped_to}
            return list(self._get_paginated("/equities/bars/daily", clamped_params, "data"))

    def fetch_fins_summary(self, code: str) -> list[dict[str, Any]]:
        params = {"code": pad_security_code(code)}
        return list(self._get_paginated("/fins/summary", params, "data"))


def normalize_security(raw: dict[str, Any]) -> dict[str, Any]:
    # Field names confirmed 2026-08-12 against a live Free-plan account.
    # The wrapper key is "data" (not "equities"), and fields use short
    # abbreviated names (CoName, not CompanyName) — nothing here matched
    # the design blueprint's assumed V1-style CamelCase field names.
    code = pad_security_code(raw.get("Code") or raw.get("code") or "")
    return {
        "code": code,
        "ticker4": code[:4],
        "name_ja": raw.get("CoName") or raw.get("CompanyName"),
        "name_en": raw.get("CoNameEn") or raw.get("CompanyNameEnglish"),
        "market_code": raw.get("Mkt") or raw.get("MarketCode"),
        "sector17": raw.get("S17") or raw.get("Sector17Code"),
        "sector33": raw.get("S33") or raw.get("Sector33Code"),
        "scale_category": raw.get("ScaleCat") or raw.get("ScaleCategory"),
        # Not present in the observed /equities/master response at all
        # (no listing/delisting date field of any name was in the payload).
        # Left unmapped rather than guessed; revisit once confirmed.
        "listed_date": None,
        "delisted_date": None,
    }


def _as_bigint(value: Any) -> Optional[int]:
    """J-Quants returns volume/turnover as JSON floats (e.g. 84170500.0);
    the daily_quotes schema stores them as bigint, and Postgres rejects a
    literal with a decimal point ("invalid input syntax for type bigint") —
    confirmed live 2026-08-12. Truncating via int() is safe here since these
    are whole-share/yen counts represented with a spurious ".0"."""
    return None if value is None else int(value)


def normalize_daily_quote(raw: dict[str, Any]) -> dict[str, Any]:
    # Field names confirmed 2026-08-12 against a live Free-plan account, same
    # short-abbreviation convention as /equities/master (O/H/L/C, not
    # Open/High/Low/Close). AdjC/AdjFactor map onto columns the design
    # blueprint's schema already had but the original guessed names never hit.
    volume = raw.get("Vo") if "Vo" in raw else raw.get("Volume")
    turnover_value = raw.get("Va") if "Va" in raw else raw.get("TurnoverValue")
    return {
        "code": pad_security_code(raw.get("Code") or raw.get("code") or ""),
        "date": raw.get("Date") or raw.get("date"),
        "open": raw.get("O") if "O" in raw else raw.get("Open"),
        "high": raw.get("H") if "H" in raw else raw.get("High"),
        "low": raw.get("L") if "L" in raw else raw.get("Low"),
        "close": raw.get("C") if "C" in raw else raw.get("Close"),
        "volume": _as_bigint(volume),
        "turnover_value": _as_bigint(turnover_value),
        "adj_factor": raw.get("AdjFactor", 1.0),
        "adj_close": raw.get("AdjC"),
        "known_from": now_utc_iso(),
    }
