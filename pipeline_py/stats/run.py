"""Applies the adoption gate to stored backtest runs and records the verdict.

Gate (design blueprint section G):
  DSR > 0.95, PBO < 0.5, and a positive out-of-sample Sharpe.
Only runs clearing all three get stats_validation.passed = true, which is
what the frontend is allowed to surface.

n_trials is every strategy evaluated against this data, not just the one
being scored. Deflating by 1 would defeat the purpose — the inflation DSR
corrects for comes from the search, so the search size is the input.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from ..backtest.metrics import kurtosis, sharpe_ratio, skewness
from ..ingest.supabase_client import SupabaseUpsertClient
from .dsr import deflated_sharpe, sharpe_variance_across_trials
from .pbo import pbo_cscv
from .purged_kfold import purged_kfold

DSR_THRESHOLD = 0.95
PBO_THRESHOLD = 0.5
DEFAULT_BLOCKS = 16


def oos_sharpe_via_purged_kfold(returns: list[float], k: int = 5, label_span: int = 5) -> float:
    """Mean daily Sharpe across purged folds' test segments.

    A plain train/test split would let the fold boundary leak; purging and the
    embargo are what make this an honest out-of-sample figure.
    """
    fold_sharpes = []
    for _, test_idx in purged_kfold(len(returns), k, label_span):
        segment = [returns[i] for i in test_idx]
        if len(segment) > 1:
            fold_sharpes.append(sharpe_ratio(segment, annualize=False))
    if not fold_sharpes:
        return 0.0
    return sum(fold_sharpes) / len(fold_sharpes)


def evaluate(runs: list[dict[str, Any]], n_blocks: int = DEFAULT_BLOCKS) -> list[dict[str, Any]]:
    """runs: [{run_id, strategy, returns: [...]}, ...] — all over the same dates."""
    series = [r["returns"] for r in runs]
    if not series or not series[0]:
        return []

    # PBO needs every strategy on a common timeline, so truncate to the
    # shortest rather than padding (padding invents periods).
    length = min(len(s) for s in series)
    matrix = [[s[t] for s in series] for t in range(length)]

    pbo_result = pbo_cscv(matrix, n_blocks=n_blocks)

    daily_sharpes = [sharpe_ratio(s[:length], annualize=False) for s in series]
    var_sr = sharpe_variance_across_trials(daily_sharpes)
    n_trials = len(runs)

    out = []
    for i, run in enumerate(runs):
        r = run["returns"][:length]
        sr = daily_sharpes[i]
        sk = skewness(r)
        ku = kurtosis(r)
        dsr, sr0 = deflated_sharpe(sr, var_sr, n_trials, len(r), sk, ku)
        oos = oos_sharpe_via_purged_kfold(r)

        pbo = pbo_result.get("pbo")
        passed = bool(
            dsr > DSR_THRESHOLD
            and pbo is not None
            and pbo < PBO_THRESHOLD
            and oos > 0
        )
        out.append(
            {
                "run_id": run["run_id"],
                "strategy": run["strategy"],
                "sharpe_daily": sr,
                "dsr": dsr,
                "psr_vs_zero": None,
                "expected_max_sharpe": sr0,
                "pbo": pbo,
                "oos_sharpe": oos,
                "n_trials": n_trials,
                "skew": sk,
                "kurtosis": ku,
                "passed": passed,
            }
        )
    return out


def load_runs(db: SupabaseUpsertClient) -> list[dict[str, Any]]:
    rows = db.select_all(
        "backtest_runs",
        {"select": "id,strategy_id,params", "order": "id.asc"},
    )
    strategies = {
        s["id"]: s["name"] for s in db.select_all("strategies", {"select": "id,name"})
    }
    runs = []
    for row in rows:
        params = row.get("params") or {}
        returns = params.get("returns")
        if not returns:
            continue
        runs.append(
            {
                "run_id": row["id"],
                "strategy": strategies.get(row["strategy_id"], str(row["strategy_id"])),
                "returns": [float(x) for x in returns],
            }
        )
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DSR / PBO / purged-KFold validation")
    parser.add_argument("--blocks", type=int, default=DEFAULT_BLOCKS)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)

    with SupabaseUpsertClient() as db:
        runs = load_runs(db)
        if not runs:
            raise RuntimeError("No backtest runs with a stored return series to validate")
        print(f"[stats] validating {len(runs)} runs", flush=True)

        results = evaluate(runs, n_blocks=args.blocks)
        for r in results:
            pbo_text = "n/a" if r["pbo"] is None else f"{r['pbo']:.4f}"
            print(
                f"[stats] {r['strategy']}: DSR={r['dsr']:.4f} PBO={pbo_text} "
                f"OOS_SR={r['oos_sharpe']:.4f} passed={r['passed']}",
                flush=True,
            )

        if args.persist:
            db.upsert(
                "stats_validation",
                [
                    {
                        "run_id": r["run_id"],
                        "dsr": r["dsr"],
                        "psr": r["psr_vs_zero"],
                        "expected_max_sharpe": r["expected_max_sharpe"],
                        "pbo": r["pbo"],
                        "n_trials": r["n_trials"],
                        "skew": r["skew"],
                        "kurtosis": r["kurtosis"],
                        "passed": r["passed"],
                    }
                    for r in results
                ],
                on_conflict="run_id",
            )
            print(f"[stats] persisted {len(results)} validations", flush=True)

        print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
