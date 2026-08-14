"""Generates trade candidates for the latest session in the feature store.

Run after build_features. Writes trade_candidates, which the UI reads.
"""
from __future__ import annotations

import argparse
import json
import sys

from ..ingest.supabase_client import SupabaseUpsertClient
from .scoring import score_theme

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
]


def latest_feature_date(db: SupabaseUpsertClient) -> str | None:
    rows = db.select("features", {"select": "date", "order": "date.desc", "limit": "1"})
    return rows[0]["date"] if rows else None


def load_snapshot(db: SupabaseUpsertClient, as_of: str) -> dict[str, dict]:
    """One row per code for as_of, joining features with that day's bar and
    the security's sector."""
    feature_rows = db.select_all(
        "features",
        {"select": "code," + ",".join(FEATURE_COLUMNS), "date": f"eq.{as_of}"},
    )
    quote_rows = db.select_all(
        "daily_quotes",
        {"select": "code,close,turnover_value", "date": f"eq.{as_of}"},
    )
    sec_rows = db.select_all(
        "securities_with_data", {"select": "code,name_ja,sector33"}
    )

    quotes = {r["code"]: r for r in quote_rows}
    secs = {r["code"]: r for r in sec_rows}

    snapshot: dict[str, dict] = {}
    for f in feature_rows:
        code = f["code"]
        q = quotes.get(code)
        s = secs.get(code)
        if not q or not s or q.get("close") is None:
            continue
        snapshot[code] = {
            **{k: f.get(k) for k in FEATURE_COLUMNS},
            "close": q["close"],
            "turnover_value": q.get("turnover_value"),
            "sector33": s.get("sector33"),
            "name_ja": s.get("name_ja"),
        }
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate themed trade candidates")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--as-of", default=None, help="Defaults to the latest feature date")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)

    with SupabaseUpsertClient() as db:
        as_of = args.as_of or latest_feature_date(db)
        if not as_of:
            raise RuntimeError("features table is empty — run build_features first")

        snapshot = load_snapshot(db, as_of)
        print(f"[screen] as_of={as_of}, {len(snapshot)} codes in snapshot", flush=True)
        if not snapshot:
            raise RuntimeError(f"no usable rows for {as_of}")

        themes = db.select_all("themes", {"select": "*", "enabled": "eq.true", "order": "sort_order.asc"})
        print(f"[screen] {len(themes)} themes", flush=True)

        all_rows = []
        summary = {}
        for theme in themes:
            horizons = ["day", "swing"] if theme["horizon"] == "both" else [theme["horizon"]]
            for horizon in horizons:
                candidates = score_theme(snapshot, theme, horizon, top_n=args.top_n)
                summary[f"{theme['key']}/{horizon}"] = [
                    {"code": c.code, "name": snapshot[c.code].get("name_ja"), "score": round(c.score, 3)}
                    for c in candidates
                ]
                for rank, c in enumerate(candidates, start=1):
                    all_rows.append(
                        {
                            "as_of": as_of,
                            "theme_key": theme["key"],
                            "code": c.code,
                            "horizon": horizon,
                            "side": c.side,
                            "rank": rank,
                            "score": c.score,
                            "entry_ref": c.entry_ref,
                            "stop_price": c.stop_price,
                            "target_price": c.target_price,
                            "atr_14": c.atr_14,
                            "rr_ratio": c.rr_ratio,
                            "rationale": c.rationale,
                        }
                    )
                print(f"[screen] {theme['key']}/{horizon}: {len(candidates)} candidates", flush=True)

        if args.persist and all_rows:
            for i in range(0, len(all_rows), 500):
                db.upsert(
                    "trade_candidates",
                    all_rows[i : i + 500],
                    on_conflict="as_of,theme_key,code,horizon",
                )
            print(f"[screen] persisted {len(all_rows)} candidates", flush=True)

        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
