import numpy as np

from ml.forecast.quick_forecast import forecast
from ml.forecast.synthetic import synthetic_ohlcv


def test_forecast_shape_and_ordering():
    res = forecast(synthetic_ohlcv("TEST", 500), horizon=5, splits=3)
    assert len(res["fan"]) == 5
    for p in res["fan"]:
        assert p["lo"] < p["mean"] < p["hi"]


def test_band_is_roughly_calibrated_out_of_sample():
    m = forecast(synthetic_ohlcv("CAL", 700), horizon=5)["metrics"]
    assert 0.7 <= m["band_coverage_80"] <= 0.9


def test_no_lookahead_labels():
    # Truncating the future must not change the in-sample feature at the cut.
    from ml.forecast.quick_forecast import build_features

    df = synthetic_ohlcv("LEAK", 300)
    a = build_features(df).iloc[199]
    b = build_features(df.iloc[:200]).iloc[199]
    assert np.allclose(a.to_numpy(), b.to_numpy(), equal_nan=True)
