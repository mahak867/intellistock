"""The real-data scorecard script: loads eod2-style CSVs, skips short or dirty files, flags suspicious jumps."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SPEC = importlib.util.spec_from_file_location("evaluate_real", Path(__file__).resolve().parents[2] / "scripts" / "evaluate_real.py")
ER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ER)


def _csv(path, n, jump=False):
    idx = pd.bdate_range("2017-01-02", periods=n)
    rng = np.random.default_rng(1)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    if jump:
        c[n // 2:] *= 0.5
    pd.DataFrame({"Date": idx, "Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": rng.integers(500, 1500, n)}).to_csv(path, index=False)


def test_load_dir_filters_short_and_flags_jumps(tmp_path):
    _csv(tmp_path / "LONG.csv", 700)
    _csv(tmp_path / "SHORT.csv", 100)
    _csv(tmp_path / "SPLIT.csv", 700, jump=True)
    data = ER.load_dir(tmp_path, "2016-01-01")
    assert set(data) == {"LONG", "SPLIT"}
    assert ER.data_flags(data["LONG"]) == []
    assert "possible unadjusted split" in ER.data_flags(data["SPLIT"])[0]


def test_forecast_reports_holdout_coverage(tmp_path):
    from ml.forecast.quick_forecast import forecast
    _csv(tmp_path / "A.csv", 900)
    df = ER.load_dir(tmp_path, "2016-01-01")["A"]
    m = forecast(df, 5)["metrics"]
    assert 0.0 <= m["band_coverage_80_holdout"] <= 1.0
    assert m["band_width_pct"] > 1.0  # a percent, not a fraction
