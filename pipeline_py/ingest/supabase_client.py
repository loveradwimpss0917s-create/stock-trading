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

    def select_all(self, table: str, params: dict[str, str], page_size: int = 1000) -> list[dict[str, Any]]:
        """Pages through a table. PostgREST caps a single response at max_rows
        (1000), so a plain select silently truncates once a table grows past
        it — which is exactly the size range securities/checkpoints sit in."""
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.select(table, {**params, "limit": str(page_size), "offset": str(offset)})
            rows.extend(page)
            if len(page) < page_size:
                return rows
            offset += page_size

    def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        resp = self.client.get(
            f"{self.url}/rest/v1/{table}",
            params=params,
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Accept": "application/json",
            },
        )
        if resp.status_code >= 400:
            print(f"[supabase] {resp.status_code} selecting from {table}: {resp.text[:500]}", flush=True)
        resp.raise_for_status()
        return resp.json()

    def insert_returning(self, table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Plain insert that returns the created rows — needed when a table's
        primary key is an identity column and a child row needs the new id."""
        if not rows:
            return []
        resp = self.client.post(
            f"{self.url}/rest/v1/{table}",
            json=rows,
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
        )
        if resp.status_code >= 400:
            print(f"[supabase] {resp.status_code} inserting into {table}: {resp.text[:500]}", flush=True)
        resp.raise_for_status()
        return resp.json()

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
        if resp.status_code >= 400:
            print(
                f"[supabase] {resp.status_code} upserting {len(rows)} rows into "
                f"{table} (on_conflict={on_conflict}): {resp.text[:1000]}",
                flush=True,
            )
            print(f"[supabase] first row sample: {rows[0]}", flush=True)
        resp.raise_for_status()

    def update(self, table: str, params: dict[str, str], patch: dict[str, Any]) -> None:
        """Partial update via PATCH — the correct PostgREST idiom for
        touching only some columns of existing rows. `upsert`'s
        INSERT ... ON CONFLICT still has Postgres validate NOT NULL columns
        omitted from the payload before it ever checks for a conflict, so a
        state-machine transition like {"state": "triggered"} would fail
        there even though the row already exists and only needs one column
        touched."""
        resp = self.client.patch(
            f"{self.url}/rest/v1/{table}",
            params=params,
            json=patch,
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        if resp.status_code >= 400:
            print(f"[supabase] {resp.status_code} updating {table}: {resp.text[:500]}", flush=True)
        resp.raise_for_status()
