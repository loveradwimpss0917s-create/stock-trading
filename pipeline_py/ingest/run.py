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
        securities = jq.fetch_equities_master()
        if not securities:
            raw = jq._get("/equities/master", {})
            print(f"[ingest] raw /equities/master response (truncated): {json.dumps(raw)[:3000]}", flush=True)
            raise RuntimeError(
                "No securities parsed from /equities/master. See raw payload above "
                "and check jquants.py's parsing against it."
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
        for i, sec in enumerate(securities):
            code = sec.get("Code") or sec.get("code")
            quotes = jq.fetch_daily_quotes(code, date_from, date_to)

            if i == 0 and quotes:
                print(f"[ingest] sample raw daily_quotes[0] for {code}: {json.dumps(quotes[0])}", flush=True)
                normalized_sample = normalize_daily_quote(quotes[0])
                if normalized_sample["close"] is None:
                    raise RuntimeError(
                        "normalize_daily_quote produced a null close price from a "
                        "non-empty response — field names in jquants.py's "
                        "normalize_daily_quote likely don't match the sample logged "
                        "above. Fix before this silently writes all-NULL rows."
                    )

            db.upsert(
                "daily_quotes",
                [normalize_daily_quote(q) for q in quotes],
                on_conflict="code,date",
            )
            total_quotes += len(quotes)
            print(f"[ingest] {code}: upserted {len(quotes)} daily_quotes rows", flush=True)

            fins = jq.fetch_fins_summary(code)
            if i == 0 and fins:
                print(f"[ingest] sample raw fins_summary[0] for {code}: {json.dumps(fins[0])}", flush=True)
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
