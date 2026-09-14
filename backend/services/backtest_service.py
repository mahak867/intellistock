"""
IntelliStock — Backtest Service
────────────────────────────────────
Thin wrapper connecting the walk-forward backtesting engine (ml/backtest)
to a loaded model + live-ish data, for the /backtesting API.
"""

from __future__ import annotations

from backend.services.model_service import ModelService
from ml.backtest.engine import run_backtest
from ml.data.pipeline import fetch_nifty50, fetch_ohlcv


class BacktestService:
    """Runs a walk-forward long/short backtest for a ticker's trained model."""

    @staticmethod
    async def run(
        ticker: str,
        backtest_days: int = 90,
        initial_capital: float = 100_000.0,
        transaction_cost_pct: float = 0.001,
        allow_short: bool = True,
    ) -> dict:
        entry = ModelService.get(ticker)
        if entry is None:
            raise ValueError(
                f"No trained model available for {ticker} — "
                f"run `python train.py --ticker {ticker}` first"
            )
        model, fe = entry["model"], entry["fe"]

        # Need enough history before the window for warm-up + sequence length,
        # so pull at least 2 years regardless of the requested backtest length.
        df = fetch_ohlcv(ticker, lookback_years=2)
        start_str = df.index[0].strftime("%Y-%m-%d")
        end_str = df.index[-1].strftime("%Y-%m-%d")
        nifty = fetch_nifty50(start=start_str, end=end_str)

        result = run_backtest(
            model=model,
            fe=fe,
            df=df,
            nifty_series=nifty,
            backtest_days=backtest_days,
            initial_capital=initial_capital,
            transaction_cost_pct=transaction_cost_pct,
            allow_short=allow_short,
        )

        return {
            "ticker": ticker,
            "backtest_days": backtest_days,
            "initial_capital": initial_capital,
            "transaction_cost_pct": transaction_cost_pct,
            "allow_short": allow_short,
            "dates": result.dates,
            "strategy_equity": [round(v, 2) for v in result.strategy_equity],
            "benchmark_equity": [round(v, 2) for v in result.benchmark_equity],
            "signals": result.signals,
            "trades": [
                {
                    "entry_date": t.entry_date,
                    "entry_price": round(t.entry_price, 2),
                    "exit_date": t.exit_date,
                    "exit_price": round(t.exit_price, 2) if t.exit_price else None,
                    "pnl_pct": round(t.pnl_pct, 2) if t.pnl_pct is not None else None,
                }
                for t in result.trades
            ],
            "strategy_metrics": result.metrics,
            "benchmark_metrics": result.benchmark_metrics,
        }
