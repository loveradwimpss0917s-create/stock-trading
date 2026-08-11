"""Idempotent upsert helper against Supabase's PostgREST (Data API), using
the service_role key — which bypasses RLS — from GitHub Actions only.

Mirrors the SQL design's `ON CONFLICT (pk) DO UPDATE` semantics via
PostgREST's `Prefer: resolution=merge-duplicates` header, so callers don't
need direct Postgres access from CI.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx


class SupabaseUpsertClient:
    def __init__(
        self,
        url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.service_role_key = service_role_key or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.client = client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "SupabaseUpsertClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
        if not rows:
            return
        resp = self.client.post(
            f"{self.url}/rest/v1/{table}",
            params={"on_conflict": on_conflict},
            json=rows,
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
        )
        resp.raise_for_status()
