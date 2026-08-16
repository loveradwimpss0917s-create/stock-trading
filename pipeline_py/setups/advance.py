"""Advances trade_plans through their state machine one session at a time:

    draft  ──(user decides BUY/WAIT)──▶ armed
    draft  ──(expires_on reached, still undecided)──▶ expired
    armed  ──(close crosses trigger_price)──▶ triggered
    armed  ──(close crosses the invalidation level first)──▶ invalidated
    armed  ──(expires_on reached, neither fired)──▶ expired

Only `draft` and `armed` are touched here. `triggered` plans wait on a
human to record the actual fill (POST /api/positions moves them to `open`)
— this batch does not auto-expire a triggered-but-unacted-on plan, which is
a real gap: there's currently no session limit on how long a plan can sit
triggered before the entry is stale. Left as a known gap rather than
inventing a threshold the design doc never specified.

Because trigger_price and the invalidation level were both resolved to
concrete numbers once, at draft time (setups/rules.py), this batch never
recomputes a rolling window — it only ever compares a session's close
against numbers already sitting on the row. That is the entire reason the
resolution step exists: the one place a look-ahead bug could hide (deriving
"the 20-day high" from bars that didn't exist when the plan was made) is
nowhere near this code.

Invalidation is checked before the trigger, but the two can never fire on
the same close: resolve_plan_levels rejects any plan where the invalidation
level sits at or above the trigger price, so a close low enough to
invalidate is always too low to have triggered. The ordering is a
convention, not a tie-break.
"""
from __future__ import annotations

import argparse
import sys

from ..ingest.supabase_client import SupabaseUpsertClient
from ..screening.evaluate import Bar

ADVANCING_STATES = ("draft", "armed")


def compute_transitions(plans: list[dict], bars_by_code: dict[str, list[Bar]], as_of: str) -> list[dict]:
    """plans: rows with id, code, state, trigger_price, invalidation (jsonb),
    expires_on. Returns [{"id": ..., "patch": {...}}] for plans whose state
    changes today. A plan with no bar dated as_of is left untouched — the
    ingest for that code simply hasn't caught up yet."""
    transitions: list[dict] = []

    for plan in plans:
        bars = bars_by_code.get(plan["code"])
        if not bars or bars[-1].date != as_of:
            continue
        close = bars[-1].close

        if plan["state"] == "draft":
            if as_of >= plan["expires_on"]:
                transitions.append({"id": plan["id"], "patch": {"state": "expired"}})
            continue

        if plan["state"] == "armed":
            inv = plan["invalidation"]
            if inv["type"] != "close_below":
                raise ValueError(f"unsupported invalidation type: {inv['type']!r}")
            if close <= inv["level"]:
                transitions.append({"id": plan["id"], "patch": {"state": "invalidated"}})
                continue

            if close >= plan["trigger_price"]:
                transitions.append(
                    {
                        "id": plan["id"],
                        "patch": {
                            "state": "triggered",
                            "triggered_on": as_of,
                            "triggered_price": close,
                        },
                    }
                )
                continue

            if as_of >= plan["expires_on"]:
                transitions.append({"id": plan["id"], "patch": {"state": "expired"}})

    return transitions


def load_bars(db: SupabaseUpsertClient, codes: set[str]) -> dict[str, list[Bar]]:
    if not codes:
        return {}
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


def run(persist: bool = False) -> list[dict]:
    with SupabaseUpsertClient() as db:
        date_rows = db.select("features", {"select": "date", "order": "date.desc", "limit": "1"})
        if not date_rows:
            raise RuntimeError("features table is empty — run build_features first")
        as_of = date_rows[0]["date"]

        plans = db.select_all(
            "trade_plans",
            {
                "select": "id,code,state,trigger_price,invalidation,expires_on",
                "state": f"in.({','.join(ADVANCING_STATES)})",
            },
        )
        print(f"[advance] as_of={as_of}, {len(plans)} draft/armed plans", flush=True)

        bars_by_code = load_bars(db, {p["code"] for p in plans})
        transitions = compute_transitions(plans, bars_by_code, as_of)
        print(f"[advance] {len(transitions)} transitions", flush=True)

        if persist:
            for t in transitions:
                db.update("trade_plans", {"id": f"eq.{t['id']}"}, t["patch"])
            print(f"[advance] persisted {len(transitions)}", flush=True)

        return transitions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Advance trade_plans' state machine")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)
    run(persist=args.persist)
    return 0


if __name__ == "__main__":
    sys.exit(main())
