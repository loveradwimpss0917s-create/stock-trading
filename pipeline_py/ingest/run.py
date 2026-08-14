"""Entry point: `python -m pipeline_py.ingest.run --mode {backfill,incremental}`.

backfill: pulls the full window the plan allows (J-Quants Free serves a
rolling ~12-week-delayed range; the client discovers the exact bounds from
the API and clamps to them).
incremental: pulls the last 7 days — the daily Cron catch-up window.

Backfilling the whole universe does not fit in one GitHub Actions run: at
4 req/min, ~4,000 companies is over 16 hours against a 6-hour job limit.
So a run takes a time budget, records per-code progress in
ingest_checkpoint, and the next run resumes where this one stopped.

financials (`/fins/summary`) is fetched but not persisted: the V2 response's
field names are unverified against the schema, and financials.known_from
must be the disclosure timestamp rather than ingestion time, so mapping it
blind would bake a look-ahead bug into the feature store.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone

from .jquants import JQuantsClient, normalize_daily_quote, normalize_security
from .supabase_client import SupabaseUpsertClient
from .universe import UNIVERSES, select_universe, sort_by_scale

BACKFILL_YEARS = 2
# Re-backfilling a code that was already done wastes the run's whole budget,
# so treat a checkpoint younger than this as still current.
CHECKPOINT_FRESH_DAYS = 7


def _code_of(raw: dict) -> str:
    return raw.get("Code") or raw.get("code") or ""


def _load_done_codes(db: SupabaseUpsertClient, fresh_days: int) -> set[str]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=fresh_days)).isoformat()
    rows = db.select_all(
        "ingest_checkpoint",
        {"select": "code,last_backfilled_at", "last_backfilled_at": f"gte.{cutoff}"},
    )
    return {r["code"] for r in rows}


def run_ingest(
    mode: str,
    limit: int | None,
    universe: str,
    max_minutes: float,
    refetch: bool,
) -> int:
    started = time.monotonic()
    deadline = started + max_minutes * 60

    with JQuantsClient.from_env() as jq, SupabaseUpsertClient() as db:
        securities = jq.fetch_equities_master()
        if not securities:
            raw = jq._get("/equities/master", {})
            print(f"[ingest] raw /equities/master (truncated): {json.dumps(raw)[:2000]}", flush=True)
            raise RuntimeError("No securities parsed from /equities/master.")
        print(f"[ingest] master: {len(securities)} codes", flush=True)

        # The master list is upserted in full — the app's search covers every
        # listed code, not just the ones with bars.
        db.upsert("securities", [normalize_security(s) for s in securities], on_conflict="code")
        print(f"[ingest] upserted {len(securities)} securities", flush=True)

        targets = sort_by_scale(select_universe(securities, universe))
        print(f"[ingest] universe={universe}: {len(targets)} codes", flush=True)

        if not refetch:
            done = _load_done_codes(db, CHECKPOINT_FRESH_DAYS)
            before = len(targets)
            targets = [s for s in targets if _code_of(s) not in done]
            print(
                f"[ingest] skipping {before - len(targets)} already backfilled "
                f"within {CHECKPOINT_FRESH_DAYS}d; {len(targets)} remaining",
                flush=True,
            )

        if limit:
            targets = targets[:limit]

        if mode == "backfill":
            date_from = (date.today() - timedelta(days=365 * BACKFILL_YEARS)).isoformat()
        else:
            date_from = (date.today() - timedelta(days=7)).isoformat()
        date_to = date.today().isoformat()

        processed = 0
        total_quotes = 0
        for i, sec in enumerate(targets):
            if time.monotonic() >= deadline:
                print(
                    f"[ingest] time budget ({max_minutes} min) reached after "
                    f"{processed} codes; remaining {len(targets) - processed} "
                    "will be picked up by the next run",
                    flush=True,
                )
                break

            code = _code_of(sec)
            try:
                quotes = jq.fetch_daily_quotes(code, date_from, date_to)

                if i == 0 and quotes:
                    print(f"[ingest] sample raw bar: {json.dumps(quotes[0])}", flush=True)
                    if normalize_daily_quote(quotes[0])["close"] is None:
                        raise RuntimeError(
                            "normalize_daily_quote produced a null close from a non-empty "
                            "response — field names no longer match the sample above."
                        )

                db.upsert(
                    "daily_quotes",
                    [normalize_daily_quote(q) for q in quotes],
                    on_conflict="code,date",
                )
                # Exercised, not persisted (see module docstring). Only on the
                # first code of a run: at 4 req/min a second call per code
                # doubles the wall clock, and 500 identical smoke tests prove
                # nothing the first one didn't.
                if processed == 0:
                    jq.fetch_fins_summary(code)

                db.upsert(
                    "ingest_checkpoint",
                    [
                        {
                            "code": code,
                            "last_backfilled_at": datetime.now(timezone.utc).isoformat(),
                            "quotes_ingested": len(quotes),
                            "last_error": None,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                    on_conflict="code",
                )
                processed += 1
                total_quotes += len(quotes)
                print(f"[ingest] {code}: {len(quotes)} bars ({processed}/{len(targets)})", flush=True)

            except Exception as exc:  # noqa: BLE001 — one bad code must not kill the run
                # Recorded without last_backfilled_at, so the next run retries it.
                print(f"[ingest] {code}: FAILED — {exc}", flush=True)
                db.upsert(
                    "ingest_checkpoint",
                    [
                        {
                            "code": code,
                            "last_error": str(exc)[:500],
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                    on_conflict="code",
                )

        elapsed = (time.monotonic() - started) / 60
        print(
            f"[ingest] done: {processed} codes, {total_quotes} bars, {elapsed:.1f} min",
            flush=True,
        )
        return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="J-Quants ingestion batch")
    parser.add_argument("--mode", choices=["backfill", "incremental"], required=True)
    parser.add_argument("--limit", type=int, default=None, help="Cap codes processed this run")
    parser.add_argument(
        "--universe",
        choices=UNIVERSES,
        default="core30",
        help="Which codes to backfill (default: core30). 'all' includes ETFs.",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=300.0,
        help="Stop starting new codes after this long (GitHub Actions caps jobs at 6h)",
    )
    parser.add_argument(
        "--refetch",
        action="store_true",
        help="Ignore checkpoints and re-fetch codes already backfilled",
    )
    args = parser.parse_args(argv)
    run_ingest(args.mode, args.limit, args.universe, args.max_minutes, args.refetch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
