"""Market Regime, built from the held universe itself rather than an index.

No index (TOPIX, Nikkei 225) is ingested — only per-name bars. Rather than
wait on that, Regime is constructed from the Breadth of the ~500 names
already tracked: what fraction sit above their 25/75-day lines, how many
advanced vs declined, how many made a fresh 20-day high or low, how spread
out today's returns were. This isn't a stand-in for a real index — it's a
direct read of the actual portfolio universe, which an index numerically
mixes together with names that aren't even in scope here.

regime_label is emphatically NOT a gate. Its validity is exactly as
unproven as every Setup's — the design's central rule is that unproven
ideas get recorded for later analysis, not used to block a trade today.
Nothing downstream may treat 'defense' as a reason to suppress a plan;
that judgment is reserved for whoever reviews Setup-by-Regime performance
once enough sessions exist to say anything statistically defensible.
"""
from __future__ import annotations

import argparse
import statistics
import sys

from ..ingest.supabase_client import SupabaseUpsertClient
from ..ingest.universe import is_operating_company
from ..screening.evaluate import Bar
from ..setups.rules import rolling_high, rolling_low

OFFENSE_MA25_MIN = 0.60
OFFENSE_ADV_DECLINE_MIN = 0.55
DEFENSE_MA25_MAX = 0.40
DEFENSE_ADV_DECLINE_MAX = 0.45


def classify(pct_above_ma25: float, adv_decline_ratio: float) -> str:
    if pct_above_ma25 >= OFFENSE_MA25_MIN and adv_decline_ratio >= OFFENSE_ADV_DECLINE_MIN:
        return "offense"
    if pct_above_ma25 <= DEFENSE_MA25_MAX and adv_decline_ratio <= DEFENSE_ADV_DECLINE_MAX:
        return "defense"
    return "neutral"


def compute_regime(
    features_by_code: dict[str, dict], bars_by_code: dict[str, list[Bar]], as_of: str
) -> dict | None:
    """One row's worth of Breadth stats for `as_of`, or None if no code in
    the universe actually has a bar dated as_of (e.g. a fully stale run)."""
    n = 0
    above_ma25 = 0
    above_ma75 = 0
    advancers = 0
    new_highs = 0
    new_lows = 0
    daily_returns: list[float] = []

    for code, feat in features_by_code.items():
        bars = bars_by_code.get(code)
        if not bars or bars[-1].date != as_of or len(bars) < 2:
            continue
        idx = len(bars) - 1
        close = bars[idx].close
        prev_close = bars[idx - 1].close
        n += 1

        ma25 = feat.get("ma_25")
        if ma25 is not None and close > float(ma25):
            above_ma25 += 1
        ma75 = feat.get("ma_75")
        if ma75 is not None and close > float(ma75):
            above_ma75 += 1
        if prev_close:
            if close > prev_close:
                advancers += 1
            daily_returns.append((close - prev_close) / prev_close)

        h20 = rolling_high(bars, idx, 20)
        l20 = rolling_low(bars, idx, 20)
        if h20 is not None and close >= h20:
            new_highs += 1
        if l20 is not None and close <= l20:
            new_lows += 1

    if n == 0:
        return None

    pct_above_ma25 = above_ma25 / n
    pct_above_ma75 = above_ma75 / n
    adv_decline_ratio = advancers / n
    dispersion = statistics.pstdev(daily_returns) if len(daily_returns) >= 2 else 0.0

    return {
        "date": as_of,
        "pct_above_ma25": round(pct_above_ma25, 4),
        "pct_above_ma75": round(pct_above_ma75, 4),
        "adv_decline_ratio": round(adv_decline_ratio, 4),
        "new_high_minus_low": new_highs - new_lows,
        "dispersion": round(dispersion, 6),
        "regime_label": classify(pct_above_ma25, adv_decline_ratio),
        "computed_from_n": n,
    }


def load_bars(db: SupabaseUpsertClient, codes: set[str]) -> dict[str, list[Bar]]:
    rows = db.select_all(
        "daily_quotes", {"select": "code,date,open,high,low,close", "order": "code.asc,date.asc"}
    )
    out: dict[str, list[Bar]] = {}
    for r in rows:
        if r["code"] not in codes or r["open"] is None or r["close"] is None:
            continue
        out.setdefault(r["code"], []).append(
            Bar(r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        )
    for bars in out.values():
        bars.sort(key=lambda b: b.date)
    return out


def run(persist: bool = False) -> dict | None:
    with SupabaseUpsertClient() as db:
        date_rows = db.select("features", {"select": "date", "order": "date.desc", "limit": "1"})
        if not date_rows:
            raise RuntimeError("features table is empty — run build_features first")
        as_of = date_rows[0]["date"]

        sec_rows = db.select_all(
            "securities_with_data", {"select": "code,sector33,scale_category"}
        )
        securities = {r["code"] for r in sec_rows if is_operating_company(r)}

        feature_rows = db.select_all(
            "features", {"select": "code,ma_25,ma_75", "date": f"eq.{as_of}"}
        )
        features_by_code = {r["code"]: r for r in feature_rows if r["code"] in securities}

        bars_by_code = load_bars(db, set(features_by_code))
        snapshot = compute_regime(features_by_code, bars_by_code, as_of)
        if snapshot is None:
            raise RuntimeError(f"no bars dated {as_of} in the universe — nothing to compute")

        print(
            f"[regime] {as_of}: {snapshot['regime_label']} "
            f"(ma25={snapshot['pct_above_ma25']:.0%}, "
            f"adv/decl={snapshot['adv_decline_ratio']:.0%}, "
            f"n={snapshot['computed_from_n']})",
            flush=True,
        )

        if persist:
            db.upsert("regime_snapshots", [snapshot], on_conflict="date")
            print("[regime] persisted", flush=True)

        return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute today's Market Regime snapshot")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)
    run(persist=args.persist)
    return 0


if __name__ == "__main__":
    sys.exit(main())
