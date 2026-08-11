"""JPX public CSV downloader — short-sale balance, margin balances, investor
type trading value, sector short-selling ratio.

J-Quants Free cannot serve these datasets (Standard/Premium only), so the
design substitutes JPX's own public CSV downloads (see design blueprint
section D). JPX's exact download paths are not part of any source verified
for this build and are known to change over time, so this adapter never
hardcodes a URL — operators must supply the current, verified URL for each
dataset via environment variables (or the `dataset_urls` constructor arg)
after confirming it from https://www.jpx.co.jp.
"""
from __future__ import annotations

import csv
import io
import os
from typing import Any, Optional

import httpx

from .common import retry_with_backoff

# dataset name -> env var an operator must set with the verified JPX CSV URL
DATASET_ENV_VARS = {
    "short_sale_balance": "JPX_CSV_URL_SHORT_SALE_BALANCE",
    "margin_balance": "JPX_CSV_URL_MARGIN_BALANCE",
    "investor_type_trading": "JPX_CSV_URL_INVESTOR_TYPE_TRADING",
    "sector_short_ratio": "JPX_CSV_URL_SECTOR_SHORT_RATIO",
}


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, httpx.TransportError)


class JpxCsvAdapter:
    def __init__(
        self,
        dataset_urls: Optional[dict[str, str]] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.client = client or httpx.Client(timeout=30.0)
        self.dataset_urls = dataset_urls or {
            name: os.environ[env_var]
            for name, env_var in DATASET_ENV_VARS.items()
            if env_var in os.environ
        }

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "JpxCsvAdapter":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_rows(self, dataset: str) -> list[dict[str, Any]]:
        url = self.dataset_urls.get(dataset)
        if not url:
            env_var = DATASET_ENV_VARS.get(dataset, "<unknown dataset>")
            raise KeyError(
                f"No URL configured for dataset '{dataset}'. Set {env_var} to "
                "the verified JPX CSV download URL before running this adapter."
            )

        def _do() -> bytes:
            resp = self.client.get(url)
            resp.raise_for_status()
            return resp.content

        raw = retry_with_backoff(_do, should_retry=_is_retryable)
        # JPX CSVs are commonly Shift-JIS encoded.
        text = raw.decode("shift-jis", errors="replace")
        return list(csv.DictReader(io.StringIO(text)))
