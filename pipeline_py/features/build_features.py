"""Builds the `features` table from `daily_quotes`.

Look-ahead safety rests on two things:

1. Every indicator is causal — out[i] uses only bars[0..i] — so a row dated
   D can only reflect information from sessions up to and including D.
2. `known_from` is stamped with D's market close (15:00 JST), i.e. the
   earliest wall-clock time the feature could actually have been computed.
   It is NOT the ingestion time: stamping "now" would make every historical
   feature look like it was knowable today, which silently defeats the
   as-of filtering the backtester depends on.

With next-open execution, a feature dated D is legitimately tradable at
D+1's open — that gap is the backtester's concern, not this module's.

Fundamental columns (per/pbr/roe/roic/accruals/gross_profitability) and the
event flags are left NULL: they need `financials`, which is not persisted
yet because the V2 field names are unverified and known_from there must be
the disclosure timestamp.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable

from ..ingest.common import JST
from ..ingest.supabase_client import SupabaseUpsertClient
from . import indicators as ind

FEATURE_SET = "v1"
# Tokyo cash equities close at 15:00 JST (15:30 from Nov 2024, but 15:00 is
# the conservative choice — an earlier stamp can only understate knowability).
MARKET_CLOSE_JST = time(15, 0)
# Longest warm-up among the indicators (ema_26 within MACD needs 26+9).
MIN_BARS = 35
UPSERT_CHUNK = 500


def market_close_utc(trade_date: str) -> str:
    d = datetime.strptime(trade_date, "%Y-%m-%d").date()
    return datetime.combine(d, MARKET_CLOSE_JST, tzinfo=JST).astimezone(timezone.utc).isoformat()


def build_rows(code: str, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """bars must be ascending by date."""
    if len(bars) < MIN_BARS:
        return []

    dates = [b["date"] for b in bars]
    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]

    ret_1d = ind.pct_return(closes, 1)
    ret_5d = ind.pct_return(closes, 5)
    ret_20d = ind.pct_return(closes, 20)
    ma_25 = ind.sma(closes, 25)
    ma_75 = ind.sma(closes, 75)
    ema_12 = ind.ema(closes, 12)
    ema_26 = ind.ema(closes, 26)
    rsi_14 = ind.rsi(closes, 14)
    macd_line, macd_signal, _ = ind.macd(closes)
    atr_14 = ind.atr(highs, lows, closes, 14)
    _, _, adx_14 = ind.adx(highs, lows, closes, 14)
    _, bb_upper, bb_lower = ind.bollinger_bands(closes, 20, 2.0)
    vol_20d = ind.realized_vol(closes, 20)
    dist_52w = ind.distance_from_high(closes, 252)

    n2n = ind.nan_to_none
    rows = []
    for i, d in enumerate(dates):
        rows.append(
            {
                "code": code,
                "date": d,
                "feature_set": FEATURE_SET,
                "ret_1d": n2n(ret_1d[i]),
                "ret_5d": n2n(ret_5d[i]),
                "ret_20d": n2n(ret_20d[i]),
                "ma_25": n2n(ma_25[i]),
                "ma_75": n2n(ma_75[i]),
                "ema_12": n2n(ema_12[i]),
                "ema_26": n2n(ema_26[i]),
                "rsi_14": n2n(rsi_14[i]),
                "macd": n2n(macd_line[i]),
                "macd_signal": n2n(macd_signal[i]),
                "atr_14": n2n(atr_14[i]),
                "adx_14": n2n(adx_14[i]),
                "bb_upper": n2n(bb_upper[i]),
                "bb_lower": n2n(bb_lower[i]),
                "vol_20d": n2n(vol_20d[i]),
                "dist_52w_high": n2n(dist_52w[i]),
                "known_from": market_close_utc(d),
            }
        )
    return rows


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def build(codes: list[str] | None = None, limit: int | None = None) -> int:
    with SupabaseUpsertClient() as db:
        if not codes:
            covered = db.select_all(
                "securities_with_data", {"select": "code", "order": "code.asc"}
            )
            codes = [r["code"] for r in covered]
        if limit:
            codes = codes[:limit]
        print(f"[features] {len(codes)} codes to process", flush=True)

        total = 0
        for code in codes:
            bars = db.select_all(
                "daily_quotes",
                {
                    "select": "date,open,high,low,close",
                    "code": f"eq.{code}",
                    "order": "date.asc",
                },
            )
            bars = [b for b in bars if b.get("close") is not None]
            rows = build_rows(code, bars)
            if not rows:
                print(f"[features] {code}: {len(bars)} bars (< {MIN_BARS}), skipped", flush=True)
                continue

            for chunk in _chunks(rows, UPSERT_CHUNK):
                db.upsert("features", chunk, on_conflict="code,date,feature_set")
            total += len(rows)
            print(f"[features] {code}: {len(rows)} rows", flush=True)

        print(f"[features] done: {total} rows across {len(codes)} codes", flush=True)
        return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the feature store from daily_quotes")
    parser.add_argument("--codes", nargs="*", help="Specific codes (default: all with bars)")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    build(args.codes, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
