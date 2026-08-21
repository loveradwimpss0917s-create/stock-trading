"""Opportunity Discovery: evaluates every enabled Setup's candidate_rule
against the latest session and drafts a trade_plan for anything that
qualifies and doesn't already have one active.

This is the batch equivalent of score_theme's top_n ranking, but with the
central change PART 4 of the design calls for: candidate_rule is an
ABSOLUTE threshold, not a relative rank. Zero qualifying names on a given
day is a normal, expected output — nothing here backfills a quota.

Draft rows have no thesis yet (see migration 0022): the batch identifies
*that* a name meets a Setup's mechanical conditions, but the sentence
explaining *why it matters right now* is written by a person when they
promote a draft to armed. That's the whole point of separating "candidate"
from "plan" — the human still has to say something true, not just click
BUY on whatever the screen ranked first.
"""
from __future__ import annotations

import argparse
import sys

from ..ingest.supabase_client import SupabaseUpsertClient
from ..ingest.universe import is_operating_company
from ..risk.cost_in_r import plan_economics
from ..screening.evaluate import Bar
from ..screening.run import FEATURE_COLUMNS
from .rules import passes_candidate_rule, resolve_plan_levels

# States that mean "this (code, setup) pairing already has a live plan" —
# a new draft must not be created on top of one of these.
ACTIVE_STATES = ("draft", "armed", "triggered", "open")


def load_bars_for_codes(
    db: SupabaseUpsertClient, codes: set[str]
) -> tuple[dict[str, list[Bar]], dict[tuple[str, str], float]]:
    rows = db.select_all(
        "daily_quotes",
        {"select": "code,date,open,high,low,close,turnover_value", "order": "code.asc,date.asc"},
    )
    out: dict[str, list[Bar]] = {}
    turnover: dict[tuple[str, str], float] = {}
    for r in rows:
        if r["code"] not in codes or r["open"] is None or r["close"] is None:
            continue
        out.setdefault(r["code"], []).append(
            Bar(r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        )
        if r.get("turnover_value") is not None:
            turnover[(r["code"], r["date"])] = float(r["turnover_value"])
    for bars in out.values():
        bars.sort(key=lambda b: b.date)
    return out, turnover


def latest_feature_date(db: SupabaseUpsertClient) -> str | None:
    rows = db.select("features", {"select": "date", "order": "date.desc", "limit": "1"})
    return rows[0]["date"] if rows else None


def run_scan(top_n_per_setup: int | None = None, persist: bool = False) -> list[dict]:
    with SupabaseUpsertClient() as db:
        as_of = latest_feature_date(db)
        if not as_of:
            raise RuntimeError("features table is empty — run build_features first")
        print(f"[scan] as_of={as_of}", flush=True)

        setups = db.select_all("setups", {"select": "*", "enabled": "eq.true", "order": "sort_order.asc"})
        print(f"[scan] {len(setups)} enabled setups", flush=True)

        sec_rows = db.select_all(
            "securities_with_data", {"select": "code,name_ja,sector33,scale_category"}
        )
        securities = {r["code"]: r for r in sec_rows if is_operating_company(r)}

        feature_rows = db.select_all(
            "features",
            {"select": "code," + ",".join(FEATURE_COLUMNS), "date": f"eq.{as_of}"},
        )
        features_by_code = {r["code"]: r for r in feature_rows if r["code"] in securities}
        print(f"[scan] {len(features_by_code)} codes with features on {as_of}", flush=True)

        bars_by_code, turnover_by_date = load_bars_for_codes(db, set(features_by_code))

        account_rows = db.select_all("accounts", {"select": "id", "order": "id.asc", "limit": "1"})
        if not account_rows:
            raise RuntimeError("no account row — apply migration 0020 (seeds a default account)")
        account_id = account_rows[0]["id"]

        active_plans = db.select_all(
            "trade_plans",
            {"select": "code,setup_key", "state": f"in.({','.join(ACTIVE_STATES)})"},
        )
        active_pairs = {(r["code"], r["setup_key"]) for r in active_plans}
        print(f"[scan] {len(active_pairs)} (code,setup) pairs already active", flush=True)

        drafts: list[dict] = []
        for setup in setups:
            n_for_setup = 0
            for code, feat in features_by_code.items():
                if (code, setup["key"]) in active_pairs:
                    continue
                bars = bars_by_code.get(code)
                if not bars or bars[-1].date != as_of:
                    continue
                idx = len(bars) - 1

                row = dict(feat)
                row["close"] = bars[idx].close
                row["turnover_value"] = turnover_by_date.get((code, as_of))

                if not passes_candidate_rule(setup["candidate_rule"], row, bars, idx):
                    continue

                levels = resolve_plan_levels(setup, bars, idx, feat)
                if levels is None:
                    continue

                # Screen on R:R NET of the round trip. Drafting on the gross
                # figure lets through plans whose entire advertised edge is
                # spent getting in and out — at a 1.0x ATR stop that is about
                # 0.2R, against selection effects measured here at 0.05R.
                econ = plan_economics(
                    levels.trigger_price,
                    levels.stop_planned,
                    levels.target_planned,
                    feat.get("atr_14"),
                )
                if econ is None or econ.rr_net < setup["min_rr"]:
                    continue

                drafts.append(
                    {
                        "account_id": account_id,
                        "code": code,
                        "setup_key": setup["key"],
                        "created_on": as_of,
                        "state": "draft",
                        "reference_close": bars[idx].close,
                        "trigger_price": levels.trigger_price,
                        "trigger_condition": levels.trigger_condition,
                        "stop_planned": levels.stop_planned,
                        "target_planned": levels.target_planned,
                        "time_stop_bars": setup["time_stop_bars"],
                        "expires_on": levels.expires_on,
                        "invalidation": levels.invalidation,
                        # expected_rr stays gross so the column keeps the
                        # meaning rows written before this change carry; the
                        # tradeable figure lives beside it rather than
                        # silently replacing it.
                        "expected_rr": round(econ.rr_gross, 3),
                        "expected_rr_net": round(econ.rr_net, 3),
                        "expected_cost_r": round(econ.cost_win_r + econ.cost_loss_r, 4),
                    }
                )
                n_for_setup += 1
                if top_n_per_setup and n_for_setup >= top_n_per_setup:
                    break
            print(f"[scan] {setup['key']}: {n_for_setup} new drafts", flush=True)

        if persist and drafts:
            created = db.insert_returning("trade_plans", drafts)
            print(f"[scan] persisted {len(created)} draft plans", flush=True)

        return drafts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft trade_plans from Setup candidate rules")
    parser.add_argument("--top-n-per-setup", type=int, default=None)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)
    run_scan(top_n_per_setup=args.top_n_per_setup, persist=args.persist)
    return 0


if __name__ == "__main__":
    sys.exit(main())
