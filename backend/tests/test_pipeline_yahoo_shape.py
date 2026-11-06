"""Yahoo frames in the shapes yfinance returns (old flat, new MultiIndex, tz-aware) must survive calendar alignment."""
import numpy as np
import pandas as pd
import pytest

from ml.data import pipeline as P


def _frame(multi: bool, tz: str | None):
    days = pd.bdate_range("2026-09-01", "2026-10-30")
    idx = days.tz_localize(tz) if tz else days
    data = {c: np.linspace(100, 110, len(days)) for c in ("Open", "High", "Low", "Close")} | {"Volume": np.full(len(days), 1000.0)}
    df = pd.DataFrame(data, index=idx)
    if multi:
        df.columns = pd.MultiIndex.from_product([df.columns, ["TCS.NS"]], names=["Price", "Ticker"])
    return df


@pytest.mark.parametrize("multi,tz", [(False, None), (True, None), (True, "Asia/Kolkata"), (True, "UTC")])
def test_fetch_ohlcv_keeps_rows(monkeypatch, tmp_path, multi, tz):
    monkeypatch.setattr(P, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(P, "_fetch_raw", lambda *a, **k: _frame(multi, tz))
    df = P.fetch_ohlcv("TCS", start="2026-09-01", end="2026-10-30", use_cache=False)
    assert len(df) >= 35 and df["Close"].notna().all()
    assert (df.index == df.index.normalize()).all()


def test_trading_days_are_dates():
    d = P.get_nse_trading_days("2026-10-01", "2026-10-10")
    assert len(d) >= 5 and (d == d.normalize()).all()
