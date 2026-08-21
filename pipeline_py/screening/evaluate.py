"""Replays the screen over history and records what each candidate did next.

The screening tab says which names a theme picks. This says whether picking
them worked, which is a different question and the one that decides whether
a theme is worth looking at.

The replay is honest about entry and exit:

  * A candidate for `as_of` is built from features known at `as_of` only.
  * The fill is the NEXT session's open, matching the backtester. The gap
    between the reference close and that open is part of the result, not
    something to wish away.
  * Barriers are checked on the following bars' high/low. Daily bars cannot
    say which side a bar touched first, so a bar touching both counts as the
    stop — the conservative reading.
  * R is measured against the stop the screen actually published, from the
    price actually paid.

What this is NOT: out-of-sample validation. Every session in the window is
used, and the themes were written while looking at this same data. A
flattering hit rate here is exactly what the DSR/PBO gate exists to
distrust. Treat it as a description of what happened, not as evidence of an
edge.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Optional

from ..ingest.supabase_client import SupabaseUpsertClient
from ..ingest.universe import is_operating_company
from .run import FEATURE_COLUMNS
from .scoring import levels_for, score_theme

# Sessions a position is given before it is closed at the market.
# A day candidate is entered at the open and closed at that session's close;
# a swing candidate gets two trading weeks to reach a 3.0x ATR target.
MAX_HOLD = {"day": 1, "swing": 10}


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Outcome:
    outcome: str  # target | stop | timeout | no_entry
    entry_fill: Optional[float]
    exit_price: Optional[float]
    exit_date: Optional[str]
    bars_held: int
    r_multiple: Optional[float]


def evaluate(
    bars: list[Bar], entry_idx: int, stop: float, target: float, max_hold: int
) -> Outcome:
    """bars[entry_idx] is the session the position is opened in, filled at its
    open. Barriers may trigger within that same session."""
    if entry_idx < 0 or entry_idx >= len(bars):
        return Outcome("no_entry", None, None, None, 0, None)

    fill = bars[entry_idx].open
    risk = fill - stop
    if risk <= 0:
        # The open already gapped through the stop. Buying here would mean
        # entering a position that is beyond its own risk limit before it
        # starts, so the screen simply does not get the trade.
        return Outcome("no_entry", fill, None, None, 0, None)
    if fill >= target:
        # The open gapped past the profit target too. Nobody buys a name
        # that has already gone where they were hoping it would go, so this
        # is a trade that does not happen — not a 0R win.
        #
        # Recording it as a target hit, which is what falls out of the
        # barrier walk if this case isn't caught, is doubly wrong: it adds
        # to the count of targets reached AND drags their average return
        # toward zero, so the Setup looks like it hits its target more often
        # and for less than it really does.
        return Outcome("no_entry", fill, None, None, 0, None)

    last = min(entry_idx + max_hold - 1, len(bars) - 1)
    for i in range(entry_idx, last + 1):
        bar = bars[i]
        held = i - entry_idx + 1
        # Stop first: a daily bar that traded through both levels gives no
        # information about the order, and assuming the good one flatters
        # every result that follows.
        if bar.low <= stop:
            # A gap straight through the stop fills at the open, not at the
            # stop price.
            exit_price = min(stop, bar.open)
            return Outcome(
                "stop", fill, exit_price, bar.date, held, (exit_price - fill) / risk
            )
        if bar.high >= target:
            exit_price = max(target, bar.open)
            return Outcome(
                "target", fill, exit_price, bar.date, held, (exit_price - fill) / risk
            )

    final = bars[last]
    return Outcome(
        "timeout",
        fill,
        final.close,
        final.date,
        last - entry_idx + 1,
        (final.close - fill) / risk,
    )


def load_bars(db: SupabaseUpsertClient) -> dict[str, list[Bar]]:
    """Every bar, once, keyed by code and sorted by date. The replay touches
    each code on many dates, so paging this per candidate would be thousands
    of round trips."""
    rows = db.select_all(
        "daily_quotes", {"select": "code,date,open,high,low,close", "order": "code.asc,date.asc"}
    )
    out: dict[str, list[Bar]] = {}
    for r in rows:
        if r["open"] is None or r["close"] is None:
            continue
        out.setdefault(r["code"], []).append(
            Bar(r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        )
    for bars in out.values():
        bars.sort(key=lambda b: b.date)
    return out


def load_features(db: SupabaseUpsertClient) -> dict[str, dict[str, dict]]:
    """date -> code -> feature row."""
    rows = db.select_all(
        "features", {"select": "code,date," + ",".join(FEATURE_COLUMNS), "order": "date.asc"}
    )
    by_date: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_date.setdefault(r["date"], {})[r["code"]] = r
    return by_date


def replay(
    features_by_date: dict[str, dict[str, dict]],
    bars_by_code: dict[str, list[Bar]],
    securities: dict[str, dict],
    themes: list[dict],
    dates: list[str],
    top_n: int,
    turnover_by_date: dict[tuple[str, str], float] | None = None,
) -> list[dict]:
    # date -> index, per code, so the session after as_of is an O(1) lookup.
    index_by_code = {
        code: {b.date: i for i, b in enumerate(bars)} for code, bars in bars_by_code.items()
    }
    turnover_by_date = turnover_by_date or {}

    rows: list[dict] = []
    for as_of in dates:
        feats = features_by_date.get(as_of, {})
        snapshot: dict[str, dict] = {}
        for code, f in feats.items():
            sec = securities.get(code)
            idx = index_by_code.get(code, {}).get(as_of)
            if not sec or idx is None:
                continue
            snapshot[code] = {
                **{k: f.get(k) for k in FEATURE_COLUMNS},
                "close": bars_by_code[code][idx].close,
                "turnover_value": turnover_by_date.get((code, as_of)),
                "sector33": sec.get("sector33"),
                "name_ja": sec.get("name_ja"),
            }
        if not snapshot:
            continue

        for theme in themes:
            horizons = ["day", "swing"] if theme["horizon"] == "both" else [theme["horizon"]]
            for horizon in horizons:
                for rank, cand in enumerate(
                    score_theme(snapshot, theme, horizon, top_n=top_n), start=1
                ):
                    bars = bars_by_code[cand.code]
                    entry_idx = index_by_code[cand.code][as_of] + 1  # next session's open
                    if entry_idx >= len(bars):
                        continue  # no session after as_of yet — nothing to judge
                    out = evaluate(
                        bars, entry_idx, cand.stop_price, cand.target_price, MAX_HOLD[horizon]
                    )
                    rows.append(
                        {
                            "as_of": as_of,
                            "theme_key": theme["key"],
                            "code": cand.code,
                            "horizon": horizon,
                            "rank": rank,
                            "entry_fill": out.entry_fill,
                            "stop_price": cand.stop_price,
                            "target_price": cand.target_price,
                            "exit_price": out.exit_price,
                            "exit_date": out.exit_date,
                            "bars_held": out.bars_held,
                            "outcome": out.outcome,
                            "r_multiple": out.r_multiple,
                        }
                    )
    return rows


def baseline(
    features_by_date: dict[str, dict[str, dict]],
    bars_by_code: dict[str, list[Bar]],
    securities: dict[str, dict],
    dates: list[str],
    turnover_by_date: dict[tuple[str, str], float] | None = None,
) -> list[dict]:
    """The control: buy EVERY eligible name, same sessions, same levels.

    Without this the theme numbers are unreadable. This window was a rising
    market, and a long-only screen returns a positive R in a rising market
    whether or not its picks were any good. What a theme has to beat is not
    zero — it is this.
    """
    index_by_code = {
        code: {b.date: i for i, b in enumerate(bars)} for code, bars in bars_by_code.items()
    }
    turnover_by_date = turnover_by_date or {}

    out_rows: list[dict] = []
    for as_of in dates:
        per_horizon: dict[str, dict[str, float]] = {
            h: {"n": 0, "no_entry": 0, "sum_r": 0.0, "wins": 0} for h in MAX_HOLD
        }
        for code, f in features_by_date.get(as_of, {}).items():
            sec = securities.get(code)
            idx = index_by_code.get(code, {}).get(as_of)
            if not sec or idx is None:
                continue
            row = {
                **{k: f.get(k) for k in FEATURE_COLUMNS},
                "close": bars_by_code[code][idx].close,
                "turnover_value": turnover_by_date.get((code, as_of)),
            }
            for horizon in MAX_HOLD:
                levels = levels_for(row, horizon)
                if levels is None:
                    continue
                _close, _atr, stop, target = levels
                bars = bars_by_code[code]
                if idx + 1 >= len(bars):
                    continue
                res = evaluate(bars, idx + 1, stop, target, MAX_HOLD[horizon])
                acc = per_horizon[horizon]
                if res.outcome == "no_entry":
                    acc["no_entry"] += 1
                    continue
                acc["n"] += 1
                acc["sum_r"] += res.r_multiple or 0.0
                if (res.r_multiple or 0.0) > 0:
                    acc["wins"] += 1

        for horizon, acc in per_horizon.items():
            if acc["n"] == 0:
                continue
            out_rows.append(
                {
                    "as_of": as_of,
                    "horizon": horizon,
                    "n_trades": int(acc["n"]),
                    "n_no_entry": int(acc["no_entry"]),
                    "sum_r": round(acc["sum_r"], 6),
                    "n_wins": int(acc["wins"]),
                }
            )
    return out_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the screen and score its candidates")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument(
        "--every",
        type=int,
        default=5,
        help="Replay every Nth session (5 = weekly). Overlapping daily windows "
        "mostly re-measure the same move.",
    )
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)

    with SupabaseUpsertClient() as db:
        print("[eval] loading bars…", flush=True)
        bars_by_code = load_bars(db)
        print(f"[eval] {sum(len(v) for v in bars_by_code.values())} bars, {len(bars_by_code)} codes", flush=True)

        print("[eval] loading features…", flush=True)
        features_by_date = load_features(db)
        print(f"[eval] {len(features_by_date)} feature dates", flush=True)

        sec_rows = db.select_all(
            "securities_with_data", {"select": "code,name_ja,sector33,scale_category"}
        )
        securities = {r["code"]: r for r in sec_rows if is_operating_company(r)}

        # Turnover drives the liquidity filter but is not on Bar, which the
        # barrier loop runs over for every candidate.
        turnover_rows = db.select_all(
            "daily_quotes", {"select": "code,date,turnover_value", "order": "code.asc,date.asc"}
        )
        turnover = {
            (r["code"], r["date"]): r["turnover_value"]
            for r in turnover_rows
            if r["turnover_value"] is not None
        }

        themes = db.select_all(
            "themes", {"select": "*", "enabled": "eq.true", "order": "sort_order.asc"}
        )

        # The last MAX_HOLD sessions cannot be judged yet — their windows run
        # past the end of the data — so they are excluded rather than counted
        # as timeouts at whatever the final bar happened to be.
        all_dates = sorted(features_by_date)
        judgeable = all_dates[: -(max(MAX_HOLD.values()) + 1)] or []
        dates = judgeable[:: args.every]
        print(f"[eval] replaying {len(dates)} sessions of {len(all_dates)}", flush=True)

        rows = replay(
            features_by_date, bars_by_code, securities, themes, dates, args.top_n, turnover
        )
        print(f"[eval] {len(rows)} candidate outcomes", flush=True)
        if not rows:
            raise RuntimeError("replay produced nothing — check features and themes")

        base = baseline(features_by_date, bars_by_code, securities, dates, turnover)
        print(f"[eval] {len(base)} baseline session rows", flush=True)
        for h in sorted(MAX_HOLD):
            hb = [b for b in base if b["horizon"] == h]
            n = sum(b["n_trades"] for b in hb)
            if n:
                print(
                    f"[eval] baseline {h}: {n} trades, avg "
                    f"{sum(b['sum_r'] for b in hb) / n:+.4f}R",
                    flush=True,
                )

        if args.persist:
            for i in range(0, len(rows), 500):
                db.upsert(
                    "candidate_outcomes",
                    rows[i : i + 500],
                    on_conflict="as_of,theme_key,code,horizon",
                )
            print(f"[eval] persisted {len(rows)} outcomes", flush=True)
            for i in range(0, len(base), 500):
                db.upsert("screen_baseline", base[i : i + 500], on_conflict="as_of,horizon")
            print(f"[eval] persisted {len(base)} baseline rows", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
