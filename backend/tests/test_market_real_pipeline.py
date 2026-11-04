"""End to end: an NSE-shaped local store (built from synthetic series, with one split injected) served through the API."""
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.data import providers, store
from ml.forecast.synthetic import synthetic_ohlcv

NAMES = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "WIPRO", "ONGC", "NTPC", "COALINDIA", "TECHM"]
M = "/api/v1/market"


@pytest.fixture(scope="module")
def nse(tmp_path_factory):
    d = tmp_path_factory.mktemp("nse")
    frames = []
    for n in NAMES:
        o = synthetic_ohlcv(n, 1000)
        r = o.copy()
        pc = r["close"].shift(1)
        if n == "ITC":  # 2-for-1 split 300 days from the end: raw prices halve from that day on, exchange prev close is halved
            i = len(r) - 300
            r.iloc[i:, r.columns.get_indexer(["open", "high", "low", "close"])] *= 0.5
            pc = pd.concat([r["close"].shift(1).iloc[:i], r["close"].shift(1).iloc[i:]])
            pc.iloc[i] = r["close"].iloc[i - 1] * 0.5
        frames.append(pd.DataFrame({"date": r.index, "symbol": n, "series": "EQ", "open": r["open"], "high": r["high"], "low": r["low"],
                                    "close": r["close"], "prev_close": pc.bfill().values, "volume": r["volume"]}))
    pd.concat(frames).to_csv(d / "prices.csv.gz", index=False, compression="gzip")
    providers.settings.DATA_PROVIDER, providers.settings.DATA_DIR = "nse", str(d)
    store._cache.clear()
    yield d
    providers.settings.DATA_PROVIDER, providers.settings.DATA_DIR = "synthetic", "./data"
    store._cache.clear()


@pytest.fixture
def c(nse):
    return TestClient(app)


def test_status_reports_real_data(c):
    s = c.get(f"{M}/status").json()
    assert s["real_data"] is True and s["symbols"] == len(NAMES)


def test_split_is_detected_and_series_stays_continuous(c):
    j = c.get(f"{M}/forecast/ITC?horizon=5").json()
    assert j["synthetic"] is False and j["source"] == "nse"
    assert len(j["quality"]["corporate_actions_adjusted"]) == 1
    closes = pd.Series([x["close"] for x in j["candles"]])
    assert closes.pct_change().abs().max() < 0.2  # no 50% cliff


def test_forecast_screener_backtest_and_risk_use_real_source(c):
    f = c.get(f"{M}/forecast/TCS?horizon=5").json()
    assert f["metrics"]["walk_forward_samples"] > 100 and len(f["fan"]) == 5
    s = c.get(f"{M}/screener").json()
    assert s["synthetic"] is False and s["universe"] >= 10
    b = c.get(f"{M}/backtest/TCS").json()
    assert b["synthetic"] is False and 0 < b["walk_forward_out_of_sample"]["time_in_market"] < 1
    r = c.post(f"{M}/portfolio-risk", json={"csv": "symbol,qty,avg_price\nTCS,10,100\nINFY,20,100\nITC,50,100\n"}).json()
    assert r["synthetic"] is False and "average of" in r["market_proxy"] and len(r["stress"]) == 2


def test_unknown_symbol_is_404_not_fake_data(c):
    r = c.get(f"{M}/forecast/NOSUCH")
    assert r.status_code == 404 and "No data for NOSUCH" in r.json()["detail"]
    assert c.get(f"{M}/quotes?tickers=TCS,NOSUCH").json()[0]["ticker"] == "TCS"


def test_forecast_rejects_degenerate_history_with_a_clear_message():
    import numpy as np
    import pytest

    from ml.forecast.quick_forecast import forecast
    from ml.forecast.synthetic import synthetic_ohlcv

    base = synthetic_ohlcv("TCS", 400)
    flat = base.copy()
    for c in ("open", "high", "low", "close"):
        flat[c] = 100.0
    for bad in (flat, base.tail(60), base.assign(volume=0)):
        with pytest.raises(ValueError, match="(?i)at least 250|too few"):
            forecast(bad, 10)


def test_forecast_ignores_row_order_and_duplicate_dates():
    import pandas as pd

    from ml.forecast.quick_forecast import forecast
    from ml.forecast.synthetic import synthetic_ohlcv

    base = synthetic_ohlcv("INFY", 400)
    messy = pd.concat([base, base.tail(5)]).sample(frac=1, random_state=3)
    a, b = forecast(base, 10), forecast(messy, 10)
    assert a["fan"][-1]["mean"] == b["fan"][-1]["mean"]
