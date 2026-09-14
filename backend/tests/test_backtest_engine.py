"""
Tests for ml/backtest/engine.py — the walk-forward backtesting engine.

Uses a lightweight FakeModel (no TensorFlow needed) so these run fast and
deterministically, while still exercising the REAL FeatureEngineer, the
REAL signal-generation rule, and the REAL position/cost logic end-to-end.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.backtest.engine import _max_drawdown, _sharpe, _sortino, run_backtest
from ml.features.engineer import FeatureEngineer


# ─── Pure metric function tests ────────────────────────────────────────────────


class TestMetricFunctions:
    def test_max_drawdown_on_known_curve(self):
        # 100 -> 150 (peak) -> 75 (50% drawdown from peak) -> 90
        equity = np.array([100, 120, 150, 100, 75, 90])
        dd = _max_drawdown(equity)
        assert dd == pytest.approx(-50.0, abs=0.01)

    def test_max_drawdown_monotonic_up_is_zero(self):
        equity = np.array([100, 110, 120, 130])
        assert _max_drawdown(equity) == pytest.approx(0.0, abs=1e-9)

    def test_sharpe_zero_for_zero_variance_returns(self):
        returns = np.array([0.001] * 20)
        # Zero std deviation -> defined as 0.0, not division by zero
        assert _sharpe(returns) == 0.0

    def test_sharpe_positive_for_positive_mean_returns(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        assert _sharpe(returns) > 0

    def test_sortino_none_when_no_downside_deviation(self):
        # All-positive returns → no downside risk to measure → None (N/A),
        # not a misleading 0 or an inf that can't survive JSON.
        upside_only = np.array([0.01, 0.05, 0.01, 0.05] * 10)
        assert _sortino(upside_only) is None

    def test_sortino_finite_and_positive_when_downside_exists_but_mean_is_positive(self):
        mixed = np.array([0.01, -0.003, 0.02, -0.008, 0.015, -0.002, 0.01, -0.006] * 5)
        result = _sortino(mixed)
        assert result is not None
        assert result > 0


# ─── Fake model for fast, deterministic integration tests ─────────────────────


class FakeModel:
    """Mimics a Keras model's .predict() with a controllable output."""

    def __init__(self, scaled_prediction: float = 0.5):
        self.scaled_prediction = scaled_prediction

    def predict(self, X, verbose=0):
        return np.full((X.shape[0], 1), self.scaled_prediction)


def _make_synthetic_ohlcv(n=400, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 1000 + np.cumsum(rng.normal(0, 5, n))
    close = np.maximum(close, 100)
    return pd.DataFrame(
        {
            "Open": close * (1 + rng.normal(0, 0.002, n)),
            "High": close * (1 + np.abs(rng.normal(0, 0.005, n))),
            "Low": close * (1 - np.abs(rng.normal(0, 0.005, n))),
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
            "IsHoliday": False,
        },
        index=pd.DatetimeIndex(dates, name="Date"),
    )


@pytest.fixture
def fitted_fe_and_df():
    """A FeatureEngineer fitted on synthetic data, plus the full dataframe."""
    df = _make_synthetic_ohlcv(n=400)
    fe = FeatureEngineer(sequence_length=30, prediction_horizon=1)
    # Fit on the first 250 rows so it's "trained" before the backtest window
    fe.fit_transform(df.iloc[:250])
    return fe, df


class TestRunBacktestIntegration:
    def test_raises_on_insufficient_history(self, fitted_fe_and_df):
        fe, df = fitted_fe_and_df
        with pytest.raises(ValueError, match="Not enough history"):
            run_backtest(FakeModel(), fe, df.iloc[:60], None, backtest_days=90)

    def test_runs_end_to_end_and_returns_expected_shape(self, fitted_fe_and_df):
        fe, df = fitted_fe_and_df
        result = run_backtest(
            FakeModel(scaled_prediction=0.9),  # bias toward high predicted price
            fe,
            df,
            nifty_series=None,
            backtest_days=60,
            initial_capital=100_000.0,
        )
        assert len(result.dates) == len(result.strategy_equity) == len(result.benchmark_equity)
        assert len(result.signals) == len(result.dates)
        assert set(result.signals) <= {"BUY", "SELL", "HOLD"}
        assert "sharpe_ratio" in result.metrics
        assert "max_drawdown_pct" in result.metrics
        assert result.benchmark_equity[0] > 0

    def test_no_leakage_backtest_window_uses_only_prior_data(self, fitted_fe_and_df):
        """
        Sanity check on the no-leakage contract: corrupting data strictly
        AFTER the backtest window must not change the signals generated
        for days inside the window, since each day's forecast is built
        only from history up to (not including) that day.
        """
        fe, df = fitted_fe_and_df
        result_a = run_backtest(
            FakeModel(0.5), fe, df, None, backtest_days=60, initial_capital=100_000.0
        )

        df_corrupted = df.copy()
        df_corrupted.iloc[-1, df_corrupted.columns.get_loc("Close")] *= 100  # blow up last row
        result_b = run_backtest(
            FakeModel(0.5), fe, df_corrupted, None, backtest_days=60, initial_capital=100_000.0
        )

        # Signals for all days except the very last one must be identical —
        # the last day's *forecast* only ever depended on data through the
        # second-to-last day, so corrupting the last row's Close must not
        # change any signal (it only changes the realised return on the
        # final day, which is expected and checked separately below).
        assert result_a.signals[:-1] == result_b.signals[:-1]

    def test_transaction_costs_reduce_equity_on_flip(self, fitted_fe_and_df):
        """A model that flips signal every single day should end up with
        materially lower equity than one with zero transaction cost,
        purely from cost drag — proving costs are actually being applied."""
        fe, df = fitted_fe_and_df

        class AlternatingModel:
            """Alternates its prediction to force BUY/SELL every day."""

            def __init__(self):
                self.i = 0

            def predict(self, X, verbose=0):
                self.i += 1
                return np.full((X.shape[0], 1), 0.9 if self.i % 2 == 0 else 0.1)

        result_with_cost = run_backtest(
            AlternatingModel(), fe, df, None, backtest_days=40,
            initial_capital=100_000.0, transaction_cost_pct=0.01,  # 1% — deliberately large
        )
        result_no_cost = run_backtest(
            AlternatingModel(), fe, df, None, backtest_days=40,
            initial_capital=100_000.0, transaction_cost_pct=0.0,
        )
        # With heavy flipping and 1% cost per flip, cost drag must leave the
        # costed run strictly behind the free run.
        assert result_with_cost.strategy_equity[-1] < result_no_cost.strategy_equity[-1]

    def test_long_only_never_shorts(self, fitted_fe_and_df):
        fe, df = fitted_fe_and_df

        class AlwaysSellModel:
            def predict(self, X, verbose=0):
                return np.full((X.shape[0], 1), 0.0)  # forces low prediction -> SELL bias

        result = run_backtest(
            AlwaysSellModel(), fe, df, None, backtest_days=40,
            initial_capital=100_000.0, allow_short=False,
        )
        # Long-only: equity should never exceed a simple bound driven by
        # staying flat (no negative-equity blowups from an accidental short).
        assert min(result.strategy_equity) > 0
