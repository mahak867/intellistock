"""
IntelliStock — Backtesting Engine
─────────────────────────────────────
A walk-forward, day-by-day trade simulator — not a static prediction log.

For every day in the backtest window, this engine:
  1. Builds the model's input purely from data strictly BEFORE that day
     (no leakage — the same discipline as the training pipeline).
  2. Gets the model's next-day forecast and the RSI/MACD-confirmed signal.
  3. Applies a simple long/flat position rule: BUY → enter or hold long,
     SELL → exit to flat, HOLD → keep current position.
  4. Charges a transaction cost on every entry/exit (default 10 bps, a
     reasonable stand-in for Indian brokerage + STT + exchange charges on
     a discount broker) so the equity curve reflects real trading friction,
     not a frictionless simulation.

Reports the same risk-adjusted metrics a professional would actually look
at — Sharpe, Sortino, max drawdown, Calmar, win rate, profit factor —
against a buy-and-hold benchmark over the identical window. Directional
accuracy alone (what Section VI of the paper reports) is not a trading
result; this is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass
class Trade:
    entry_date: str
    entry_price: float
    exit_date: str | None = None
    exit_price: float | None = None
    pnl_pct: float | None = None


@dataclass
class BacktestResult:
    dates: list[str]
    strategy_equity: list[float]
    benchmark_equity: list[float]
    signals: list[str]
    trades: list[Trade]
    metrics: dict
    benchmark_metrics: dict


def _max_drawdown(equity: np.ndarray) -> float:
    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    return float(drawdown.min()) * 100  # percent, negative


def _sharpe(daily_returns: np.ndarray, rf_daily: float = 0.0) -> float:
    excess = daily_returns - rf_daily
    std = excess.std(ddof=1)
    if std < 1e-9:  # effectively zero variance — avoid blowing up on FP noise
        return 0.0
    return float(excess.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR))


def _sortino(daily_returns: np.ndarray, rf_daily: float = 0.0) -> float | None:
    """
    None (→ "N/A" in the API/UI) when there's no downside deviation to
    measure against — that's the best case, not a neutral 0. A flat/positive
    stream isn't "no benefit," it's "no measured downside risk."
    """
    excess = daily_returns - rf_daily
    downside = excess[excess < 0]
    if len(downside) == 0:
        return None
    downside_std = downside.std(ddof=1)
    if downside_std < 1e-9:
        return None
    return float(excess.mean() / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR))


def _compute_metrics(equity: np.ndarray, trades: list[Trade]) -> dict:
    n_days = len(equity) - 1
    total_return_pct = float((equity[-1] / equity[0] - 1) * 100)
    years = max(n_days / TRADING_DAYS_PER_YEAR, 1e-9)
    cagr_pct = float(((equity[-1] / equity[0]) ** (1 / years) - 1) * 100)
    daily_returns = np.diff(equity) / equity[:-1]
    max_dd_pct = _max_drawdown(equity)
    sharpe = _sharpe(daily_returns)
    sortino = _sortino(daily_returns)
    calmar = float(cagr_pct / abs(max_dd_pct)) if abs(max_dd_pct) > 1e-9 else None

    closed = [t for t in trades if t.pnl_pct is not None]
    wins = [t for t in closed if t.pnl_pct > 0]
    losses = [t for t in closed if t.pnl_pct <= 0]
    win_rate_pct = float(len(wins) / len(closed) * 100) if closed else 0.0
    gross_profit = sum(t.pnl_pct for t in wins)
    gross_loss = abs(sum(t.pnl_pct for t in losses))
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0
    )

    return {
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2) if sortino is not None else None,
        "calmar_ratio": round(calmar, 2) if calmar is not None else None,
        "win_rate_pct": round(win_rate_pct, 2),
        "num_trades": len(closed),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
    }


def run_backtest(
    model,
    fe,
    df: pd.DataFrame,
    nifty_series: pd.Series | None,
    backtest_days: int = 90,
    initial_capital: float = 100_000.0,
    transaction_cost_pct: float = 0.001,
    allow_short: bool = True,
) -> BacktestResult:
    """
    Walk-forward backtest over the LAST `backtest_days` trading days of `df`.

    `df` must contain enough history BEFORE the backtest window to satisfy
    the feature engineer's warm-up + sequence-length requirements for the
    very first simulated day (same constraint as live prediction).

    Position sizing uses the standard sign(position) x daily-return
    compounding method (long = +1, short = -1, flat = 0) rather than
    literal share counts, which is the conventional way to simulate a
    long/short overlay without modelling margin mechanics. A long-only
    (`allow_short=False`) variant is also supported for a more conservative
    comparison.
    """
    from ml.features.engineer import MAX_WARMUP, compute_features, generate_signal

    seq_len = fe.sequence_length
    min_history = seq_len + MAX_WARMUP

    if len(df) < min_history + backtest_days:
        raise ValueError(
            f"Not enough history: need {min_history + backtest_days} rows, "
            f"got {len(df)}. Reduce backtest_days or extend the data lookback."
        )

    sim_start = len(df) - backtest_days
    dates: list[str] = []
    signals: list[str] = []
    strategy_equity = [initial_capital]
    benchmark_equity = [initial_capital]
    trades: list[Trade] = []

    equity = initial_capital
    position = 0  # -1 short, 0 flat, +1 long
    open_trade: Trade | None = None
    bench_entry_price = float(df["Close"].iloc[sim_start - 1])

    for i in range(sim_start, len(df)):
        history = df.iloc[:i]  # strictly before day i — no leakage
        today = df.iloc[i]
        prev_price = float(df["Close"].iloc[i - 1])
        actual_price_today = float(today["Close"])
        daily_return = (actual_price_today - prev_price) / prev_price
        date_str = str(df.index[i].date()) if hasattr(df.index[i], "date") else str(df.index[i])

        # ── Model forecast for "today" using only data through yesterday ──
        X, _ = fe.transform(history, nifty_series=nifty_series)
        if len(X) == 0:
            continue
        pred_scaled = model.predict(X[-1:], verbose=0).flatten()
        predicted_price = float(fe.inverse_transform_close(pred_scaled)[0])

        feat_row = compute_features(history).dropna().iloc[-1]
        sig = generate_signal(
            predicted_price=predicted_price,
            current_price=prev_price,
            rsi=float(feat_row["RSI"]),
            macd=float(feat_row["MACD"]),
            macd_signal=float(feat_row["MACD_Signal"]),
        )
        signal = sig["signal"]
        signals.append(signal)
        dates.append(date_str)

        target_position = {"BUY": 1, "SELL": -1 if allow_short else 0, "HOLD": position}.get(
            signal, position
        )

        # ── Apply today's P&L at YESTERDAY's position, then rebalance ──────
        equity *= 1 + position * daily_return

        if target_position != position:
            equity -= equity * transaction_cost_pct  # cost to flip/exit
            if position != 0 and open_trade:
                open_trade.exit_date = date_str
                open_trade.exit_price = prev_price
                open_trade.pnl_pct = position * (prev_price - open_trade.entry_price) / open_trade.entry_price * 100
                trades.append(open_trade)
                open_trade = None
            if target_position != 0:
                equity -= equity * transaction_cost_pct  # cost to enter new side
                open_trade = Trade(entry_date=date_str, entry_price=prev_price)
            position = target_position

        strategy_equity.append(equity)
        benchmark_equity.append(initial_capital * actual_price_today / bench_entry_price)

    # Close any position still open at the end of the window (mark-to-market)
    if open_trade and position != 0:
        last_price = float(df["Close"].iloc[-1])
        open_trade.exit_date = dates[-1] if dates else None
        open_trade.exit_price = last_price
        open_trade.pnl_pct = position * (last_price - open_trade.entry_price) / open_trade.entry_price * 100
        trades.append(open_trade)

    strategy_metrics = _compute_metrics(np.array(strategy_equity), trades)
    bh_trade = Trade(
        entry_date=dates[0] if dates else "",
        entry_price=bench_entry_price,
        exit_date=dates[-1] if dates else "",
        exit_price=float(df["Close"].iloc[-1]),
        pnl_pct=(float(df["Close"].iloc[-1]) / bench_entry_price - 1) * 100,
    )
    benchmark_metrics = _compute_metrics(np.array(benchmark_equity), [bh_trade])

    return BacktestResult(
        dates=dates,
        strategy_equity=strategy_equity[1:],
        benchmark_equity=benchmark_equity[1:],
        signals=signals,
        trades=trades,
        metrics=strategy_metrics,
        benchmark_metrics=benchmark_metrics,
    )
