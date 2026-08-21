"""Historical outcomes for the Setup system — the Shadow Book that
candidate_outcomes/evaluate.py already built for the old theme screens,
rebuilt on Setup rules instead of theme rank.

This exists for two things:

1. Edge Discovery (design PART 11): a real n of judged (code, setup, as_of)
   triples to run against the baseline below and a t-stat, the same
   discipline theme_edge already applies — not a claim that any Setup here
   is validated yet.
2. Replay training (PART 2's answer to the sample-size problem: at ~250
   trades/year and a per-trade R stdev of 1.2-1.9, detecting a real edge
   needs on the order of 1,800 trades — about 7 years live). Feeding a past
   session's candidates to the UI with the outcome held back turns 84 days
   of delay into practice reps instead of dead time.

`walk_plan` mirrors the live state machine exactly: a candidate is drafted
on `as_of`, then each following session is checked against the SAME frozen
levels advance.py compares — invalidation first, then trigger — and the
fill only happens on the session after the trigger actually fires. An
earlier version of this module bought unconditionally on as_of+1 while
still measuring risk from trigger_price, i.e. from a price that was never
paid; every R it produced was distorted. If the runtime ever stops waiting
for the trigger, this must stop waiting too, or the Shadow Book stops
describing the thing being run.

The barrier walk itself reuses screening.evaluate.evaluate(): same
conservative rules as the theme screens — a bar touching both stop and
target counts as the stop, a gap through the stop fills at the open.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from ..ingest.supabase_client import SupabaseUpsertClient
from ..ingest.universe import is_operating_company
from ..risk.cost_in_r import cost_in_r
from ..screening.evaluate import Bar, evaluate
from ..screening.run import FEATURE_COLUMNS
from .rules import passes_candidate_rule, resolve_plan_levels

# Outcomes where no position was ever opened, so there is no R to average.
# Kept as rows rather than dropped: how often a Setup fails to trigger at
# all is part of what it costs to run, and silently discarding those makes
# the survivors look better than the Setup is.
NON_TRADE_OUTCOMES = ("expired", "invalidated", "no_entry")


def walk_plan(
    bars: list[Bar],
    idx: int,
    trigger_price: float,
    invalidation_level: float,
    stop: float,
    target: float,
    expiry_bars: int,
    time_stop_bars: int,
) -> Optional[dict]:
    """Runs one drafted plan forward exactly as advance.py would.

    Returns None when the data runs out before a verdict is possible — an
    unjudgeable plan must not be recorded as a timeout, which would count
    "we ran out of history" as a real result.
    """
    last_watch = min(idx + expiry_bars, len(bars) - 1)

    for i in range(idx + 1, last_watch + 1):
        close = bars[i].close

        # Same order as advance.py. resolve_plan_levels guarantees
        # invalidation < trigger, so these can never both fire on one close;
        # the ordering is a convention, not a tie-break.
        if close <= invalidation_level:
            return {"outcome": "invalidated", "exit_date": bars[i].date, "bars_held": 0}

        if close >= trigger_price:
            entry_idx = i + 1
            if entry_idx >= len(bars):
                return None  # triggered, but no session left to fill on
            out = evaluate(bars, entry_idx, stop, target, time_stop_bars)
            return {
                "outcome": out.outcome,
                "entry_fill": out.entry_fill,
                "exit_price": out.exit_price,
                "exit_date": out.exit_date,
                "bars_held": out.bars_held,
                "r_multiple": out.r_multiple,
                "triggered_on": bars[i].date,
            }

    if last_watch < idx + expiry_bars:
        return None  # window ran past the end of the data — not yet judgeable
    return {"outcome": "expired", "exit_date": bars[last_watch].date, "bars_held": 0}


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

                result = walk_plan(
                    bars,
                    idx,
                    levels.trigger_price,
                    levels.invalidation["level"],
                    levels.stop_planned,
                    levels.target_planned,
                    setup["expiry_bars"],
                    setup["time_stop_bars"],
                )
                if result is None:
                    continue

                # Gross R is not takeable. A plan that never filled has no
                # execution cost at all, so cost_r stays null there rather
                # than defaulting to zero and being averaged in as a trade.
                cost_r = None
                if result.get("entry_fill") is not None and result.get("exit_price") is not None:
                    cost_r = cost_in_r(
                        result["entry_fill"],
                        result["exit_price"],
                        levels.stop_planned,
                        float(feat["atr_14"]),
                    )

                rows.append(
                    {
                        "as_of": as_of,
                        "setup_key": setup["key"],
                        "code": code,
                        "trigger_price": levels.trigger_price,
                        "stop_planned": levels.stop_planned,
                        "target_planned": levels.target_planned,
                        "entry_fill": result.get("entry_fill"),
                        "exit_price": result.get("exit_price"),
                        "exit_date": result.get("exit_date"),
                        "bars_held": result.get("bars_held"),
                        "outcome": result["outcome"],
                        "r_multiple": result.get("r_multiple"),
                        "cost_r": cost_r,
                    }
                )
    return rows


def baseline(
    features_by_date: dict[str, dict[str, dict]],
    bars_by_code: dict[str, list[Bar]],
    securities: dict[str, dict],
    setups: list[dict],
    dates: list[str],
    turnover_by_date: dict[tuple[str, str], float],
) -> list[dict]:
    """The control: on the same sessions, buy EVERY tradable name at the
    next open under the same ATR multiples, with no signal condition at all.

    Without this the Setup numbers are unreadable. The replay window is a
    rising market, and a long-only screen posts a positive R in one whether
    or not its picks were any good — exactly what the theme system's
    +0.28R turned out to be once screen_baseline was subtracted.

    Two deliberate asymmetries, both of which make the control HARDER to
    beat rather than easier:

    * Only the liquidity floor from candidate_rule is applied, never the
      signal conditions. "Buy everything" has to mean everything actually
      tradable, not everything including names too thin to fill.
    * The control does not wait for a trigger — it buys on as_of+1. Waiting
      is part of what a Setup does, so the Setup has to earn its keep
      against not waiting, not against a differently-timed version of
      itself. Stop and target are therefore measured from the reference
      close (the price a no-signal buyer would be working from), not from
      a trigger level that only exists inside the Setup.
    """
    index_by_code = {
        code: {b.date: i for i, b in enumerate(bars)} for code, bars in bars_by_code.items()
    }

    out_rows: list[dict] = []
    for as_of in dates:
        feats = features_by_date.get(as_of, {})
        for setup in setups:
            min_turnover = setup["candidate_rule"].get("min_turnover")
            stop_mult = setup["stop_rule"]["mult"]
            target_mult = setup["target_rule"]["mult"]

            acc = {"n": 0, "no_entry": 0, "sum_r": 0.0, "sum_cost_r": 0.0, "wins": 0}
            for code, feat in feats.items():
                if code not in securities:
                    continue
                bars = bars_by_code.get(code)
                if not bars:
                    continue
                idx = index_by_code[code].get(as_of)
                if idx is None or idx + 1 >= len(bars):
                    continue

                atr = feat.get("atr_14")
                if atr is None or float(atr) <= 0:
                    continue
                if min_turnover is not None:
                    turnover = turnover_by_date.get((code, as_of))
                    if turnover is None or turnover < min_turnover:
                        continue

                close = bars[idx].close
                atr = float(atr)
                stop = close - stop_mult * atr
                res = evaluate(
                    bars, idx + 1, stop, close + target_mult * atr, setup["time_stop_bars"]
                )
                if res.outcome == "no_entry":
                    acc["no_entry"] += 1
                    continue
                acc["n"] += 1
                acc["sum_r"] += res.r_multiple or 0.0
                # The control pays execution too. Charging the Setup but not
                # the baseline would hand the Setup a free head start of
                # roughly 0.1R and quietly invert the comparison.
                if res.entry_fill is not None and res.exit_price is not None:
                    c = cost_in_r(res.entry_fill, res.exit_price, stop, atr)
                    acc["sum_cost_r"] += c or 0.0
                if (res.r_multiple or 0.0) > 0:
                    acc["wins"] += 1

            if acc["n"] == 0:
                continue
            out_rows.append(
                {
                    "as_of": as_of,
                    "setup_key": setup["key"],
                    "n_trades": int(acc["n"]),
                    "n_no_entry": int(acc["no_entry"]),
                    "sum_r": round(acc["sum_r"], 6),
                    "sum_cost_r": round(acc["sum_cost_r"], 6),
                    "n_wins": int(acc["wins"]),
                }
            )
    return out_rows


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
    parser = argparse.ArgumentParser(description="Replay Setup rules over history")
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

        # A plan needs expiry_bars to watch for a trigger, one more session
        # to fill on, and time_stop_bars to run — anything closer to the end
        # of the data can't reach a verdict.
        tail = max((s["expiry_bars"] + s["time_stop_bars"] + 1 for s in setups), default=16)
        all_dates = sorted(features_by_date)
        judgeable = all_dates[:-tail] if len(all_dates) > tail else []
        dates = judgeable[:: args.every]
        print(f"[setup-replay] replaying {len(dates)} of {len(all_dates)} sessions", flush=True)

        rows = replay(features_by_date, bars_by_code, securities, setups, dates, turnover)
        traded = [r for r in rows if r["outcome"] not in NON_TRADE_OUTCOMES]
        print(f"[setup-replay] {len(rows)} plans, {len(traded)} reached a fill", flush=True)

        base = baseline(features_by_date, bars_by_code, securities, setups, dates, turnover)
        for s in setups:
            sb = [b for b in base if b["setup_key"] == s["key"]]
            n = sum(b["n_trades"] for b in sb)
            if n:
                gross = sum(b["sum_r"] for b in sb) / n
                cost = sum(b["sum_cost_r"] for b in sb) / n
                print(
                    f"[setup-replay] baseline {s['key']}: {n} trades, "
                    f"gross {gross:+.4f}R  cost {cost:.4f}R  net {gross - cost:+.4f}R",
                    flush=True,
                )

        for s in setups:
            sr = [r for r in traded if r["setup_key"] == s["key"] and r["cost_r"] is not None]
            if sr:
                gross = sum(r["r_multiple"] or 0.0 for r in sr) / len(sr)
                cost = sum(r["cost_r"] for r in sr) / len(sr)
                print(
                    f"[setup-replay] {s['key']}: {len(sr)} trades, "
                    f"gross {gross:+.4f}R  cost {cost:.4f}R  net {gross - cost:+.4f}R",
                    flush=True,
                )

        if args.persist and rows:
            for i in range(0, len(rows), 500):
                db.upsert("setup_outcomes", rows[i : i + 500], on_conflict="as_of,setup_key,code")
            print(f"[setup-replay] persisted {len(rows)} outcomes", flush=True)
            for i in range(0, len(base), 500):
                db.upsert("setup_baseline", base[i : i + 500], on_conflict="as_of,setup_key")
            print(f"[setup-replay] persisted {len(base)} baseline rows", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
