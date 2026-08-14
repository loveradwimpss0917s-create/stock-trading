"""Runs strategies against the feature store and records results.

Writes backtest_runs / backtest_metrics. The daily return series is kept on
the run row because the statistical validation layer (DSR/PBO) needs the
raw series, not just the summary metrics — and it must be the *daily*
series, since a Sharpe computed at one frequency and deflated at another is
silently wrong.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from ..ingest.supabase_client import SupabaseUpsertClient
from .engine import Bar, FeatureRow, run_backtest
from .strategies import default_strategies

FEATURE_COLUMNS = [
    "ret_1d",
    "ret_5d",
    "ret_20d",
    "rsi_14",
    "atr_14",
    "adx_14",
    "vol_20d",
    "dist_52w_high",
    "ma_25",
    "ma_75",
    "macd",
    "macd_signal",
]


def load_data(db: SupabaseUpsertClient, codes: list[str] | None = None):
    if not codes:
        rows = db.select_all("securities_with_data", {"select": "code", "order": "code.asc"})
        codes = [r["code"] for r in rows]

    bars: dict[str, dict[str, Bar]] = {}
    features: dict[str, dict[str, FeatureRow]] = {}
    all_dates: set[str] = set()

    for code in codes:
        quote_rows = db.select_all(
            "daily_quotes",
            {"select": "date,open,high,low,close", "code": f"eq.{code}", "order": "date.asc"},
        )
        usable = {}
        for r in quote_rows:
            if r["close"] is None or r["open"] is None:
                continue
            usable[r["date"]] = Bar(
                date=r["date"],
                open=float(r["open"]),
                high=float(r["high"]) if r["high"] is not None else float(r["open"]),
                low=float(r["low"]) if r["low"] is not None else float(r["open"]),
                close=float(r["close"]),
            )
        if not usable:
            continue
        bars[code] = usable
        all_dates.update(usable)

        feature_rows = db.select_all(
            "features",
            {
                "select": "date," + ",".join(FEATURE_COLUMNS),
                "code": f"eq.{code}",
                "order": "date.asc",
            },
        )
        features[code] = {
            r["date"]: FeatureRow(
                code=code,
                date=r["date"],
                values={k: (float(r[k]) if r.get(k) is not None else None) for k in FEATURE_COLUMNS},
            )
            for r in feature_rows
        }

    return bars, features, sorted(all_dates)


def persist(db: SupabaseUpsertClient, result, strategy_id: int, n_trials: int) -> None:
    m = result.metrics
    # backtest_runs.id is an identity column; PostgREST returns the inserted
    # row when asked, which is how the metrics row gets its FK.
    inserted = db.insert_returning(
        "backtest_runs",
        [
            {
                "strategy_id": strategy_id,
                "params": {
                    **result.params,
                    "returns": result.returns,  # DSR/PBO consume this daily series
                    "dates": result.dates,
                },
                "period_start": result.dates[0] if result.dates else None,
                "period_end": result.dates[-1] if result.dates else None,
                "n_trials": n_trials,
            }
        ],
    )
    run_id = inserted[0]["id"]

    db.upsert(
        "backtest_metrics",
        [
            {
                "run_id": run_id,
                "expectancy": m.expectancy,
                "profit_factor": None if m.profit_factor == float("inf") else m.profit_factor,
                "sharpe": m.sharpe,
                "sortino": m.sortino,
                "calmar": m.calmar,
                "max_dd": m.max_drawdown,
                "win_rate": m.win_rate,
                "n_trades": m.n_trades,
                "avg_holding_days": m.avg_holding_days,
                "turnover": m.turnover,
            }
        ],
        on_conflict="run_id",
    )
    print(f"[backtest] {result.strategy}: run_id={run_id}", flush=True)


def ensure_strategy(db: SupabaseUpsertClient, name: str, definition: dict) -> int:
    db.upsert("strategies", [{"name": name, "definition": definition}], on_conflict="name")
    rows = db.select("strategies", {"select": "id", "name": f"eq.{name}", "limit": "1"})
    return rows[0]["id"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run backtests over the feature store")
    parser.add_argument("--rebalance-every", type=int, default=5)
    parser.add_argument("--n-side", type=int, default=5, help="Names per leg")
    parser.add_argument("--warmup", type=int, default=75, help="Bars to skip while indicators warm up")
    parser.add_argument("--persist", action="store_true", help="Write results to Supabase")
    args = parser.parse_args(argv)

    with SupabaseUpsertClient() as db:
        bars, features, calendar = load_data(db)
        print(f"[backtest] {len(bars)} codes, {len(calendar)} sessions", flush=True)
        if len(calendar) <= args.warmup:
            raise RuntimeError(
                f"calendar ({len(calendar)}) is shorter than warmup ({args.warmup})"
            )

        strategies = default_strategies(n_side=args.n_side)
        results = []
        for strat in strategies:
            result = run_backtest(
                strat,
                bars,
                features,
                calendar,
                rebalance_every=args.rebalance_every,
                warmup=args.warmup,
            )
            m = result.metrics
            print(
                f"[backtest] {result.strategy}: sharpe={m.sharpe:.3f} "
                f"(daily={m.sharpe_daily:.4f}) maxDD={m.max_drawdown:.3f} "
                f"trades={m.n_trades} win={m.win_rate:.3f}",
                flush=True,
            )
            results.append(result)

        if args.persist:
            # n_trials is what DSR deflates by: every strategy tried against
            # this data counts, not just the one being reported.
            n_trials = len(results)
            for strat, result in zip(strategies, results):
                sid = ensure_strategy(
                    db,
                    strat.name,
                    {"n_side": args.n_side, "rebalance_every": args.rebalance_every},
                )
                persist(db, result, sid, n_trials)

        print(json.dumps({r.strategy: r.metrics.to_dict() for r in results}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
