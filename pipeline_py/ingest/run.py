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
import json
import sys
from datetime import date, timedelta

from .jquants import JQuantsClient, normalize_daily_quote, normalize_security
from .supabase_client import SupabaseUpsertClient

BACKFILL_YEARS = 2


def run_ingest(mode: str, limit: int | None) -> None:
    with JQuantsClient.from_env() as jq, SupabaseUpsertClient() as db:
        raw_master = jq._get("/equities/master", {})
        print(f"[ingest] /equities/master raw top-level keys: {list(raw_master.keys())}", flush=True)

        securities = raw_master.get("equities", [])
        if not securities:
            # Our assumed response shape (items under an "equities" key) didn't
            # match — dump enough of the raw payload to fix the parsing, and
            # fail loudly instead of silently completing with 0 rows.
            print(f"[ingest] raw response (truncated): {json.dumps(raw_master)[:3000]}", flush=True)
            raise RuntimeError(
                "No securities parsed from /equities/master — response shape did not "
                "match the assumed 'equities' key. See raw payload above and fix "
                "jquants.py's parsing accordingly."
            )
        print(f"[ingest] fetched {len(securities)} securities from /equities/master", flush=True)

        if limit:
            securities = securities[:limit]
        print(f"[ingest] processing {len(securities)} securities (limit={limit})", flush=True)

        db.upsert("securities", [normalize_security(s) for s in securities], on_conflict="code")
        print(f"[ingest] upserted {len(securities)} rows into securities", flush=True)

        if mode == "backfill":
            date_from = (date.today() - timedelta(days=365 * BACKFILL_YEARS)).isoformat()
        else:
            date_from = (date.today() - timedelta(days=7)).isoformat()
        date_to = date.today().isoformat()

        total_quotes = 0
        for sec in securities:
            code = sec.get("Code") or sec.get("code")
            quotes = jq.fetch_daily_quotes(code, date_from, date_to)
            db.upsert(
                "daily_quotes",
                [normalize_daily_quote(q) for q in quotes],
                on_conflict="code,date",
            )
            total_quotes += len(quotes)
            print(f"[ingest] {code}: upserted {len(quotes)} daily_quotes rows", flush=True)
            jq.fetch_fins_summary(code)  # exercised, not yet persisted — see module docstring
        print(f"[ingest] done: {len(securities)} securities, {total_quotes} daily_quotes rows total", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="J-Quants ingestion batch")
    parser.add_argument("--mode", choices=["backfill", "incremental"], required=True)
    parser.add_argument("--limit", type=int, default=None, help="Limit securities count (smoke tests)")
    args = parser.parse_args(argv)
    run_ingest(args.mode, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
