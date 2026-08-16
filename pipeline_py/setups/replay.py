"""Historical outcomes for the new Setup system — the Shadow Book that
candidate_outcomes/evaluate.py already built for the old theme screens,
rebuilt on Setup rules instead of theme rank.

This exists for two things:

1. Edge Discovery (design PART 11): a real n of judged (code, setup, as_of)
   triples to eventually run against a baseline and a t-stat, the same
   discipline theme_edge already applies — not a claim that any Setup here
   is validated yet.
2. Replay training (PART 2's answer to the sample-size problem: at ~250
   trades/year and a per-trade R stdev of 1.2-1.9, detecting a real edge
   needs on the order of 1,800 trades — about 7 years live). Feeding a past
   session's candidates to the UI with the outcome held back turns 84 days
   of delay into practice reps instead of dead time.

The barrier walk reuses screening.evaluate.evaluate() rather than
reimplementing it: same conservative rules apply here as to the theme
screens — a bar touching both stop and target counts as the stop, a gap
through the stop fills at the open, and a candidate_rule that resolves to
no valid levels is skipped, exactly as scan.py does for today's session.
"""
from __future__ import annotations

import argparse
import sys

from ..ingest.supabase_client import SupabaseUpsertClient
from ..ingest.universe import is_operating_company
from ..screening.evaluate import Bar, evaluate
from ..screening.run import FEATURE_COLUMNS
from .rules import passes_candidate_rule, resolve_plan_levels


def replay(
    features_by_date: dict[str, dict[str, dict]],
    bars_by_code: dict[str, list[Bar]],
    securities: dict[str, dict],
    setups: list[dict],
    dates: list[str],
    turnover_by_date: dict[tuple[str, str], float],
) -> list[dict]:
    index_by_code = {
        code: {b.date: i for i, b in enumerate(bars)} for code, bars in bars_by_code.items()
    }

    rows: list[dict] = []
    for as_of in dates:
        feats = features_by_date.get(as_of, {})
        for setup in setups:
            for code, feat in feats.items():
                if code not in securities:
                    continue
                bars = bars_by_code.get(code)
                if not bars:
                    continue
                idx = index_by_code[code].get(as_of)
                if idx is None:
                    continue

                row = dict(feat)
                row["close"] = bars[idx].close
                row["turnover_value"] = turnover_by_date.get((code, as_of))

                if not passes_candidate_rule(setup["candidate_rule"], row, bars, idx):
                    continue
                levels = resolve_plan_levels(setup, bars, idx, feat)
                if levels is None:
                    continue

                entry_idx = idx + 1
                if entry_idx >= len(bars):
                    continue  # no session after as_of yet — nothing to judge

                out = evaluate(
                    bars, entry_idx, levels.stop_planned, levels.target_planned, setup["time_stop_bars"]
                )
                rows.append(
                    {
                        "as_of": as_of,
                        "setup_key": setup["key"],
                        "code": code,
                        "trigger_price": levels.trigger_price,
                        "stop_planned": levels.stop_planned,
                        "target_planned": levels.target_planned,
                        "entry_fill": out.entry_fill,
                        "exit_price": out.exit_price,
                        "exit_date": out.exit_date,
                        "bars_held": out.bars_held,
                        "outcome": out.outcome,
                        "r_multiple": out.r_multiple,
                    }
                )
    return rows


def load_bars(db: SupabaseUpsertClient) -> tuple[dict[str, list[Bar]], dict[tuple[str, str], float]]:
    rows = db.select_all(
        "daily_quotes",
        {"select": "code,date,open,high,low,close,turnover_value", "order": "code.asc,date.asc"},
    )
    bars_by_code: dict[str, list[Bar]] = {}
    turnover: dict[tuple[str, str], float] = {}
    for r in rows:
        if r["open"] is None or r["close"] is None:
            continue
        bars_by_code.setdefault(r["code"], []).append(
            Bar(r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        )
        if r.get("turnover_value") is not None:
            turnover[(r["code"], r["date"])] = float(r["turnover_value"])
    for bars in bars_by_code.values():
        bars.sort(key=lambda b: b.date)
    return bars_by_code, turnover


def load_features(db: SupabaseUpsertClient) -> dict[str, dict[str, dict]]:
    rows = db.select_all(
        "features", {"select": "code,date," + ",".join(FEATURE_COLUMNS), "order": "date.asc"}
    )
    by_date: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_date.setdefault(r["date"], {})[r["code"]] = r
    return by_date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay Setup candidate rules over history")
    parser.add_argument("--every", type=int, default=5, help="Replay every Nth session")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)

    with SupabaseUpsertClient() as db:
        print("[setup-replay] loading bars…", flush=True)
        bars_by_code, turnover = load_bars(db)
        print(f"[setup-replay] {sum(len(v) for v in bars_by_code.values())} bars", flush=True)

        print("[setup-replay] loading features…", flush=True)
        features_by_date = load_features(db)

        sec_rows = db.select_all(
            "securities_with_data", {"select": "code,name_ja,sector33,scale_category"}
        )
        securities = {r["code"]: r for r in sec_rows if is_operating_company(r)}

        setups = db.select_all("setups", {"select": "*", "enabled": "eq.true", "order": "sort_order.asc"})

        max_time_stop = max((s["time_stop_bars"] for s in setups), default=10)
        all_dates = sorted(features_by_date)
        judgeable = all_dates[: -(max_time_stop + 1)] if len(all_dates) > max_time_stop + 1 else []
        dates = judgeable[:: args.every]
        print(f"[setup-replay] replaying {len(dates)} of {len(all_dates)} sessions", flush=True)

        rows = replay(features_by_date, bars_by_code, securities, setups, dates, turnover)
        print(f"[setup-replay] {len(rows)} outcomes", flush=True)

        if args.persist and rows:
            for i in range(0, len(rows), 500):
                db.upsert(
                    "setup_outcomes", rows[i : i + 500], on_conflict="as_of,setup_key,code"
                )
            print(f"[setup-replay] persisted {len(rows)}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
