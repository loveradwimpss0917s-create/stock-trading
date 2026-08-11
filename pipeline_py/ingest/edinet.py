"""EDINET API v2 client — documents list + document body download.

Auth is a `Subscription-Key` query parameter (issued from the EDINET
mypage), not a header. Used to detect buyback/dividend-up/PBR-improvement
disclosures that J-Quants Free cannot supply.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from .common import retry_with_backoff

BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, httpx.TransportError)


class EdinetClient:
    def __init__(
        self,
        subscription_key: str,
        base_url: str = BASE_URL,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.subscription_key = subscription_key
        self.client = client or httpx.Client(base_url=base_url, timeout=30.0)

    @classmethod
    def from_env(cls) -> "EdinetClient":
        return cls(subscription_key=os.environ["EDINET_API_KEY"])

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "EdinetClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_documents_list(self, date: str, doc_type: int = 2) -> list[dict[str, Any]]:
        """date: 'YYYY-MM-DD'. doc_type=2 returns metadata plus the document list."""

        def _do() -> dict[str, Any]:
            resp = self.client.get(
                "/documents.json",
                params={"date": date, "type": doc_type, "Subscription-Key": self.subscription_key},
            )
            resp.raise_for_status()
            return resp.json()

        payload = retry_with_backoff(_do, should_retry=_is_retryable)
        return payload.get("results", [])

    def fetch_document(self, doc_id: str, doc_type: int = 1) -> bytes:
        """doc_type: 1=XBRL zip, 2=PDF (per EDINET API spec)."""

        def _do() -> bytes:
            resp = self.client.get(
                f"/documents/{doc_id}",
                params={"type": doc_type, "Subscription-Key": self.subscription_key},
            )
            resp.raise_for_status()
            return resp.content

        return retry_with_backoff(_do, should_retry=_is_retryable)
