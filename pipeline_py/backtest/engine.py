"""Event-driven cross-sectional backtester.

The loop is: on each rebalance date D, a strategy sees features dated D or
earlier and returns target weights; those weights are filled at D+1's OPEN.
That one-session gap is the whole point of the design — a signal derived
from D's close cannot be executed at D's close, and vectorized backtests
that multiply signal[D] by return[D] book exactly that impossible trade.

Positions are held at target weight and marked daily on closes. Returns are
gross of tax (see costs.py for why) and net of slippage, commission and
borrow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Protocol

from .costs import CostModel
from .metrics import Metrics, Trade, compute_metrics


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass
class FeatureRow:
    code: str
    date: str
    values: dict[str, Optional[float]]


class Strategy(Protocol):
    name: str

    def target_weights(
        self, asof: str, features: dict[str, FeatureRow]
    ) -> dict[str, float]:
        """Map code -> target weight. Positive is long, negative is short.
        Only receives rows dated <= asof; returning a code absent from the
        universe on the fill date is tolerated and skipped."""


@dataclass
class Position:
    code: str
    side: str
    weight: float
    entry_date: str
    entry_price: float
    days_held: int = 0


@dataclass
class BacktestResult:
    strategy: str
    dates: list[str]
    returns: list[float]
    equity: list[float]
    trades: list[Trade]
    metrics: Metrics
    params: dict = field(default_factory=dict)


def _next_trading_dates(dates: list[str]) -> dict[str, str]:
    return {d: dates[i + 1] for i, d in enumerate(dates[:-1])}


def run_backtest(
    strategy: Strategy,
    bars: dict[str, dict[str, Bar]],
    features: dict[str, dict[str, FeatureRow]],
    calendar: list[str],
    cost_model: CostModel | None = None,
    rebalance_every: int = 5,
    warmup: int = 0,
) -> BacktestResult:
    """
    bars:     code -> date -> Bar
    features: code -> date -> FeatureRow
    calendar: sorted trading dates covering the test window
    """
    costs = cost_model or CostModel()
    next_date = _next_trading_dates(calendar)

    positions: dict[str, Position] = {}
    pending: Optional[tuple[str, dict[str, float]]] = None  # (fill_date, weights)
    trades: list[Trade] = []
    daily_returns: list[float] = []
    ret_dates: list[str] = []
    traded_notional = 0.0

    for i, date in enumerate(calendar):
        day_return = 0.0
        prev = calendar[i - 1] if i > 0 else None

        # 1) Execute first, at TODAY's open — a fill happens before the close
        #    it will be marked against. Doing this after the mark would drop
        #    the entry day's open->close move from the daily series while
        #    still counting it in trade PnL, so the equity curve and the
        #    trade list would measure different things (a positive Sharpe
        #    alongside a profit factor below 1 is the tell).
        if pending and pending[0] == date:
            _, targets = pending
            pending = None
            cost_drag, notional, exit_pnl = _rebalance(
                date, targets, positions, bars, features, costs, trades, prev
            )
            day_return += exit_pnl - cost_drag
            traded_notional += notional

        # 2) Mark the book to today's close. A position opened today is marked
        #    from its entry fill; one carried in is marked from yesterday's
        #    close.
        for pos in positions.values():
            bar_today = bars.get(pos.code, {}).get(date)
            if not bar_today:
                continue
            if pos.entry_date == date:
                base = pos.entry_price
            else:
                bar_prev = bars.get(pos.code, {}).get(prev) if prev else None
                if not bar_prev or not bar_prev.close:
                    continue
                base = bar_prev.close
            if not base:
                continue
            px_ret = (bar_today.close - base) / base
            signed = px_ret if pos.side == "long" else -px_ret
            day_return += pos.weight * signed
            pos.days_held += 1
            if pos.side == "short":
                day_return -= costs.borrow_cost(pos.weight, 1, "short")

        if i >= warmup:
            daily_returns.append(day_return)
            ret_dates.append(date)

        # 3) Decide, but do not execute — the fill lands on the next session.
        if i >= warmup and (i - warmup) % rebalance_every == 0:
            asof_features = {
                code: rows[date] for code, rows in features.items() if date in rows
            }
            fill_date = next_date.get(date)
            if fill_date:
                pending = (fill_date, strategy.target_weights(date, asof_features))

    # Close anything still open at the final close, so metrics see realized
    # PnL. The book was already marked to that close, so only the exit
    # slippage remains to be booked — otherwise the equity curve would omit a
    # cost the trade list charges.
    if positions and calendar:
        residual = _close_all(calendar[-1], positions, bars, features, costs, trades)
        if daily_returns:
            daily_returns[-1] += residual

    years = max(len(daily_returns) / 252, 1e-9)
    turnover = traded_notional / years
    metrics = compute_metrics(daily_returns, trades, turnover)
    from .metrics import equity_curve

    return BacktestResult(
        strategy=strategy.name,
        dates=ret_dates,
        returns=daily_returns,
        equity=equity_curve(daily_returns),
        trades=trades,
        metrics=metrics,
        params={"rebalance_every": rebalance_every, "warmup": warmup},
    )


def _atr_of(features: dict[str, dict[str, FeatureRow]], code: str, date: str) -> Optional[float]:
    row = features.get(code, {}).get(date)
    return row.values.get("atr_14") if row else None


def _rebalance(
    date: str,
    targets: dict[str, float],
    positions: dict[str, Position],
    bars: dict[str, dict[str, Bar]],
    features: dict[str, dict[str, FeatureRow]],
    costs: CostModel,
    trades: list[Trade],
    prev_date: Optional[str],
) -> tuple[float, float, float]:
    """Returns (cost_drag, traded_notional, exit_day_pnl).

    exit_day_pnl is the last leg of a closing position's return — yesterday's
    close to today's exit fill. The mark step can't produce it because the
    position is gone by then.
    """
    cost_drag = 0.0
    notional = 0.0
    exit_pnl = 0.0

    # Exit anything no longer targeted (or whose side flipped).
    for code in list(positions):
        target = targets.get(code, 0.0)
        pos = positions[code]
        same_side = (target > 0 and pos.side == "long") or (target < 0 and pos.side == "short")
        if target == 0 or not same_side:
            bar = bars.get(code, {}).get(date)
            if not bar:
                continue  # no fill available; carry the position
            fill = costs.exit_fill_price(bar.open, _atr_of(features, code, date), pos.side)

            # Final marking leg: from whatever the position was last marked at
            # (yesterday's close, or its own entry fill if it opened today) to
            # the exit fill.
            bar_prev = bars.get(code, {}).get(prev_date) if prev_date else None
            base = pos.entry_price if pos.entry_date == date else (bar_prev.close if bar_prev else None)
            if base:
                leg = (fill - base) / base
                exit_pnl += pos.weight * (leg if pos.side == "long" else -leg)

            gross = (
                (fill - pos.entry_price) / pos.entry_price
                if pos.side == "long"
                else (pos.entry_price - fill) / pos.entry_price
            )
            borrow = costs.borrow_cost(pos.weight, pos.days_held, pos.side)
            commission = costs.commission(pos.weight)
            pnl = pos.weight * gross - borrow - commission
            cost_drag += commission
            notional += abs(pos.weight)
            trades.append(
                Trade(
                    code=code,
                    entry_date=pos.entry_date,
                    exit_date=date,
                    entry_price=pos.entry_price,
                    exit_price=fill,
                    weight=pos.weight,
                    side=pos.side,
                    pnl=pnl,
                    holding_days=pos.days_held,
                    costs={"commission": commission, "borrow": borrow},
                )
            )
            del positions[code]

    # Enter new targets.
    for code, target in targets.items():
        if target == 0 or code in positions:
            continue
        bar = bars.get(code, {}).get(date)
        if not bar or not bar.open:
            continue
        side = "long" if target > 0 else "short"
        fill = costs.entry_fill_price(bar.open, _atr_of(features, code, date), side)
        weight = abs(target)
        commission = costs.commission(weight)
        cost_drag += commission
        notional += weight
        positions[code] = Position(
            code=code, side=side, weight=weight, entry_date=date, entry_price=fill
        )

    return cost_drag, notional, exit_pnl


def _close_all(
    date: str,
    positions: dict[str, Position],
    bars: dict[str, dict[str, Bar]],
    features: dict[str, dict[str, FeatureRow]],
    costs: CostModel,
    trades: list[Trade],
) -> float:
    """Returns the residual return to book — the slippage between the close the
    book was already marked at and the actual exit fill."""
    residual = 0.0
    for code, pos in list(positions.items()):
        bar = bars.get(code, {}).get(date)
        if not bar:
            continue
        fill = costs.exit_fill_price(bar.close, _atr_of(features, code, date), pos.side)
        if bar.close:
            leg = (fill - bar.close) / bar.close
            residual += pos.weight * (leg if pos.side == "long" else -leg)
        gross = (
            (fill - pos.entry_price) / pos.entry_price
            if pos.side == "long"
            else (pos.entry_price - fill) / pos.entry_price
        )
        borrow = costs.borrow_cost(pos.weight, pos.days_held, pos.side)
        commission = costs.commission(pos.weight)
        trades.append(
            Trade(
                code=code,
                entry_date=pos.entry_date,
                exit_date=date,
                entry_price=pos.entry_price,
                exit_price=fill,
                weight=pos.weight,
                side=pos.side,
                pnl=pos.weight * gross - borrow - commission,
                holding_days=pos.days_held,
                costs={"commission": commission, "borrow": borrow},
            )
        )
        del positions[code]
    return residual
