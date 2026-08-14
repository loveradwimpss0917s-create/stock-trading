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
        # 1) Mark the book on today's close, using yesterday's close as the base.
        day_return = 0.0
        if i > 0:
            prev = calendar[i - 1]
            for pos in positions.values():
                bar_today = bars.get(pos.code, {}).get(date)
                bar_prev = bars.get(pos.code, {}).get(prev)
                if not bar_today or not bar_prev or not bar_prev.close:
                    continue
                px_ret = (bar_today.close - bar_prev.close) / bar_prev.close
                signed = px_ret if pos.side == "long" else -px_ret
                day_return += pos.weight * signed
                pos.days_held += 1
                if pos.side == "short":
                    day_return -= costs.borrow_cost(pos.weight, 1, "short")

        # 2) Execute what was decided on the previous rebalance, at TODAY's open.
        if pending and pending[0] == date:
            _, targets = pending
            pending = None
            cost_drag, opened, closed, notional = _rebalance(
                date, targets, positions, bars, features, costs, trades
            )
            day_return -= cost_drag
            traded_notional += notional

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

    # Close anything still open at the final close, so metrics see realized PnL.
    if positions and calendar:
        _close_all(calendar[-1], positions, bars, features, costs, trades)

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
) -> tuple[float, int, int, float]:
    cost_drag = 0.0
    notional = 0.0
    opened = closed = 0

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
            closed += 1

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
        opened += 1

    return cost_drag, opened, closed, notional


def _close_all(
    date: str,
    positions: dict[str, Position],
    bars: dict[str, dict[str, Bar]],
    features: dict[str, dict[str, FeatureRow]],
    costs: CostModel,
    trades: list[Trade],
) -> None:
    for code, pos in list(positions.items()):
        bar = bars.get(code, {}).get(date)
        if not bar:
            continue
        fill = costs.exit_fill_price(bar.close, _atr_of(features, code, date), pos.side)
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
