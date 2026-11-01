import numpy as np

from ml.forecast.quick_forecast import build_features, forecast, vol_features
from ml.forecast.synthetic import synthetic_ohlcv


def test_shape_and_ordering():
    res = forecast(synthetic_ohlcv("TEST", 500), horizon=5, splits=3)
    assert len(res["fan"]) == 5
    for p in res["fan"]:
        assert p["lo"] < p["mean"] < p["hi"]


def test_band_is_calibrated_out_of_sample():
    m = forecast(synthetic_ohlcv("CAL", 800), horizon=5)["metrics"]
    assert 0.72 <= m["band_coverage_80"] <= 0.88


def test_random_walk_has_no_edge_and_shrinks_to_zero():
    # Direction in the synthetic series is pure noise: the model must say so.
    flags = [forecast(synthetic_ohlcv(t, 800), horizon=5)["metrics"] for t in ("A1", "B2", "C3", "D4")]
    assert sum(m["has_edge"] for m in flags) <= 1
    assert all(m["shrink"] < 0.5 for m in flags)


def test_volatility_is_forecastable():
    ms = [forecast(synthetic_ohlcv(t, 800), horizon=5)["metrics"] for t in ("A1", "B2", "C3")]
    assert sum(m["vol_beats_naive"] for m in ms) >= 2


def test_features_have_no_lookahead():
    df = synthetic_ohlcv("LEAK", 300)
    for fn in (build_features, vol_features):
        a, b = fn(df).iloc[199], fn(df.iloc[:200]).iloc[199]
        assert np.allclose(a.to_numpy(), b.to_numpy(), equal_nan=True)


def test_market_features_are_used():
    df = synthetic_ohlcv("MKT", 500)
    import pandas as pd

    mk = pd.DataFrame({"index_close": synthetic_ohlcv("IDX", 500)["close"], "vix": 15.0})
    assert forecast(df, 5, splits=3, market=mk)["metrics"]["market_features"] is True
