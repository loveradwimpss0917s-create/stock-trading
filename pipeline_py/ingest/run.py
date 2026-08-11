"""Entry point: `python -m pipeline_py.ingest.run --mode {backfill,incremental} [--limit N]`.

backfill: pulls ~2 years of daily quotes (the depth J-Quants Free retains).
incremental: pulls the last 7 days (daily Cron catch-up window).

financials (`/fins/summary`) normalization is intentionally not wired to a
Supabase upsert yet — the V2 response's exact field names are unverified
against a live account (see design blueprint Caveats), and `financials`'
bitemporal `known_from` must be the disclosure timestamp, not ingestion
wall-clock time. Fetching is exercised here so the adapter path is proven;
mapping + upsert lands once a real key allows inspecting the response shape.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from .jquants import JQuantsClient, normalize_daily_quote, normalize_security
from .supabase_client import SupabaseUpsertClient

BACKFILL_YEARS = 2


def run_ingest(mode: str, limit: int | None) -> None:
    with JQuantsClient.from_env() as jq, SupabaseUpsertClient() as db:
        securities = jq.fetch_equities_master()
        if limit:
            securities = securities[:limit]

        db.upsert("securities", [normalize_security(s) for s in securities], on_conflict="code")

        if mode == "backfill":
            date_from = (date.today() - timedelta(days=365 * BACKFILL_YEARS)).isoformat()
        else:
            date_from = (date.today() - timedelta(days=7)).isoformat()
        date_to = date.today().isoformat()

        for sec in securities:
            code = sec.get("Code") or sec.get("code")
            quotes = jq.fetch_daily_quotes(code, date_from, date_to)
            db.upsert(
                "daily_quotes",
                [normalize_daily_quote(q) for q in quotes],
                on_conflict="code,date",
            )
            jq.fetch_fins_summary(code)  # exercised, not yet persisted — see module docstring


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="J-Quants ingestion batch")
    parser.add_argument("--mode", choices=["backfill", "incremental"], required=True)
    parser.add_argument("--limit", type=int, default=None, help="Limit securities count (smoke tests)")
    args = parser.parse_args(argv)
    run_ingest(args.mode, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
