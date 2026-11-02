"""Index files, dividends, layouts, licence gate and the fixture label."""
import io
import zipfile
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.config import Environment
from backend.data import dividends as dv
from backend.data import indices, providers, store
from backend.data.bhavcopy import ALIASES, parse_udiff, resolve_columns
from backend.data.prices import build_ohlcv
from ml.forecast.synthetic import synthetic_ohlcv

# ── older NSE layouts still load ─────────────────────────────────────────────
LEGACY = "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\nTCS,EQ,100,105,99,104,104,100,5000,1,12-OCT-2026,10,INE1,\n"
FULL = "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY\nTCS, EQ, 12-Oct-2026, 100, 100, 105, 99, 104, 104, 102, 5000\n"


@pytest.mark.parametrize("raw", [LEGACY, FULL])
def test_legacy_layouts_parse(raw):
    r = parse_udiff(raw.encode(), date(2026, 10, 12)).iloc[0]
    assert r.symbol == "TCS" and r.close == 104 and r.prev_close == 100 and r.volume == 5000


def test_every_field_has_an_alias_and_missing_is_reported():
    assert set(ALIASES) == {"date", "symbol", "series", "open", "high", "low", "close", "prev_close", "volume"}
    _, missing = resolve_columns(["SYMBOL", "SERIES"])
    assert "close" in missing


# ── index files ──────────────────────────────────────────────────────────────
IDX = ("Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,Points Change,Change(%),Volume\n"
       "Nifty 50,12-10-2026,24000,24100,23900,\"24,050.5\",50,0.2,1\nIndia VIX,12-10-2026,12,13,11.5,12.4,0.1,1,0\nNifty Midcap 100,12-10-2026,1,1,1,1,0,0,0\n")


def test_index_file_parses_needed_rows_and_checks_date():
    df = indices.parse_index_file(IDX.encode(), date(2026, 10, 12))
    assert set(df["index"]) == {"NIFTY 50", "INDIA VIX"} and df.loc[df["index"] == "NIFTY 50", "close"].iloc[0] == 24050.5
    with pytest.raises(Exception, match="index file is for"):
        indices.parse_index_file(IDX.encode(), date(2026, 10, 13))
    with pytest.raises(ValueError):
        indices.parse_index_file(b"a,b\n1,2")


def test_fetch_range_also_collects_index_files(tmp_path):
    from backend.tests.test_data_layer import FakeClient, FakeResp, udiff, zipped

    days = list(store.weekdays(date(2026, 10, 5), date(2026, 10, 7)))
    by = {}
    for i, d in enumerate(days):
        by[f"{d:%Y%m%d}"] = FakeResp(200, zipped(udiff(f"{d:%Y-%m-%d}", [("TCS", "EQ", 100, 105, 99, 104, 100, 5000)])))

    class C(FakeClient):
        def get(self, url):
            if "ind_close_all" in url:
                ds = url.split("_")[-1][:8]  # DDMMYYYY
                return FakeResp(200, IDX.replace("12-10-2026", f"{ds[:2]}-{ds[2:4]}-{ds[4:]}").encode())
            return super().get(url)

    res = store.fetch_range(days[0], days[-1], tmp_path, C(by), delay=0)
    assert res["index_days"] == 3 and res["index_rows"] == 6 and not res["failed"]


# ── dividends ────────────────────────────────────────────────────────────────
def test_dividend_amounts_from_purpose_text():
    assert dv.amount_from_purpose("Interim Dividend - Rs 5 Per Share") == 5.0
    assert dv.amount_from_purpose("Final Dividend - Re 1.5 Per Share") == 1.5
    assert dv.amount_from_purpose("Dividend Rs. 12.50") == 12.5
    assert dv.amount_from_purpose("Bonus 1:1") is None and dv.amount_from_purpose("Dividend - as declared") is None


def test_parse_dividends_csv_both_shapes():
    plain = dv.parse_dividends("symbol,ex_date,amount\nTCS,2026-01-09,10\nTCS,bad,1\n")
    assert len(plain) == 1 and plain.attrs["skipped"] == 1
    nse = dv.parse_dividends("Symbol,Purpose,Ex-Date\nITC,Interim Dividend - Rs 6.5 Per Share,15-Feb-2026\nITC,Bonus 1:1,16-Feb-2026\n")
    assert nse.iloc[0].amount == 6.5 and nse.attrs["skipped"] == 1
    with pytest.raises(ValueError):
        dv.parse_dividends("a,b\n1,2")


DAYS = pd.bdate_range("2026-01-05", periods=10)


def _rows(closes, prevs=None):
    prevs = prevs or [closes[0]] + closes[:-1]
    return pd.DataFrame({"date": DAYS, "symbol": "ABC", "series": "EQ", "open": closes, "high": [c * 1.01 for c in closes],
                         "low": [c * 0.99 for c in closes], "close": closes, "prev_close": prevs, "volume": 1000.0})


def test_dividend_makes_total_return_continuous_without_touching_volume():
    closes = [100.0] * 5 + [95.0] * 5                 # Rs 5 dividend on day 6: price drops 5%
    div = pd.DataFrame({"symbol": ["ABC"], "ex_date": [DAYS[5]], "amount": [5.0]})
    plain, q0 = build_ohlcv(_rows(closes), "ABC", today=date(2026, 1, 20))
    tr, q1 = build_ohlcv(_rows(closes), "ABC", today=date(2026, 1, 20), dividends=div)
    assert q0["total_return"] is False and "NOT added back" in q0["adjusted_for"]
    assert q1["total_return"] and q1["dividends_applied"] == 1 and q1["corporate_actions_adjusted"] == []
    assert tr["close"].iloc[0] == pytest.approx(95.0) and tr["close"].iloc[-1] == 95.0
    assert tr["close"].pct_change().abs().max() < 1e-9      # no fake 5% drop
    assert (tr["volume"] == 1000.0).all()


def test_dividend_not_counted_twice_if_exchange_already_adjusted():
    closes = [100.0] * 5 + [95.0] * 5
    prevs = [100.0] * 5 + [95.0] * 5                   # exchange previous close already reduced by the dividend
    div = pd.DataFrame({"symbol": ["ABC"], "ex_date": [DAYS[5]], "amount": [5.0]})
    out, q = build_ohlcv(_rows(closes, prevs), "ABC", today=date(2026, 1, 20), dividends=div)
    assert q["dividends_applied"] == 0 and any("not counted twice" in i for i in q["issues"])
    assert out["close"].pct_change().abs().max() < 1e-9  # the exchange adjustment alone makes it continuous


def test_absurd_dividend_is_skipped():
    div = pd.DataFrame({"symbol": ["ABC"], "ex_date": [DAYS[5]], "amount": [90.0]})
    _, q = build_ohlcv(_rows([100.0] * 10), "ABC", today=date(2026, 1, 20), dividends=div)
    assert q["dividends_applied"] == 0 and any("looks wrong" in i for i in q["issues"])


# ── providers, labels, licence gate ──────────────────────────────────────────
def _store(tmp_path, names=("TCS", "INFY", "ITC", "WIPRO", "SBIN", "ONGC"), fixture=True, with_index=True):
    fr = []
    for n in names:
        r = synthetic_ohlcv(n, 700)
        fr.append(pd.DataFrame({"date": r.index, "symbol": n, "series": "EQ", "open": r.open, "high": r.high, "low": r.low, "close": r.close,
                                "prev_close": r.close.shift(1).bfill().values, "volume": r.volume}))
    pd.concat(fr).to_csv(tmp_path / "prices.csv.gz", index=False, compression="gzip")
    if fixture:
        (tmp_path / "FIXTURE").write_text("synthetic")
    if with_index:
        n50 = synthetic_ohlcv("NIFTY", 700)["close"]
        vix = synthetic_ohlcv("VIXX", 700)["close"] / 10
        pd.concat([pd.DataFrame({"date": n50.index, "index": "NIFTY 50", "close": n50.values}),
                   pd.DataFrame({"date": vix.index, "index": "INDIA VIX", "close": vix.values})]).to_csv(tmp_path / "indices.csv.gz", index=False, compression="gzip")
    store._cache.clear()


def _use(monkeypatch, tmp_path, provider="nse", licensed=False, env=None):
    monkeypatch.setattr(providers.settings, "DATA_PROVIDER", provider, raising=False)
    monkeypatch.setattr(providers.settings, "DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(providers.settings, "NSE_DATA_LICENSED", licensed, raising=False)
    if env:
        monkeypatch.setattr(providers.settings, "ENVIRONMENT", env, raising=False)


def test_fixture_is_labelled_synthetic_everywhere(tmp_path, monkeypatch):
    _store(tmp_path)
    _use(monkeypatch, tmp_path)
    p = providers.get_prices("TCS")
    assert p.source == "fixture" and p.synthetic
    st = providers.status()
    assert st["real_data"] is False and "fixture" in st["note"].lower()


def test_real_index_feeds_betas_and_market_features(tmp_path, monkeypatch):
    _store(tmp_path, fixture=False)
    _use(monkeypatch, tmp_path, licensed=True)
    c = TestClient(app)
    assert providers.status()["has_index_data"] and providers.status()["has_vix"]
    f = c.get("/api/v1/market/forecast/TCS?horizon=5").json()
    assert f["metrics"]["market_features"] is True and f["source"] == "nse"
    r = c.post("/api/v1/market/portfolio-risk", json={"csv": "symbol,qty,avg_price\nTCS,10,100\nINFY,20,100\nITC,50,100\n"}).json()
    assert r["market_proxy"] == "Nifty 50 index"


def test_without_index_files_it_says_so_and_still_works(tmp_path, monkeypatch):
    _store(tmp_path, fixture=False, with_index=False)
    _use(monkeypatch, tmp_path, licensed=True)
    c = TestClient(app)
    assert c.get("/api/v1/market/forecast/TCS?horizon=5").json()["metrics"]["market_features"] is False
    r = c.post("/api/v1/market/portfolio-risk", json={"csv": "symbol,qty,avg_price\nTCS,10,100\nINFY,20,100\nITC,50,100\n"}).json()
    assert "average of" in r["market_proxy"]


def test_production_refuses_unlicensed_nse_files_and_fixtures_and_placeholders(tmp_path, monkeypatch):
    c = TestClient(app)
    _store(tmp_path, fixture=False)
    _use(monkeypatch, tmp_path, provider="nse", licensed=False, env=Environment.PRODUCTION)
    r = c.get("/api/v1/market/status")
    assert r.status_code == 503 and "NSE Data & Analytics" in r.json()["detail"]
    _use(monkeypatch, tmp_path, provider="nse", licensed=True, env=Environment.PRODUCTION)
    assert c.get("/api/v1/market/status").status_code == 200
    _use(monkeypatch, tmp_path, provider="local", licensed=False, env=Environment.PRODUCTION)
    assert c.get("/api/v1/market/status").status_code == 200  # vendor data you licensed yourself
    (tmp_path / "FIXTURE").write_text("x")
    store._cache.clear()
    assert c.get("/api/v1/market/status").status_code == 503
    _use(monkeypatch, tmp_path, provider="synthetic", env=Environment.PRODUCTION)
    assert c.get("/api/v1/market/status").status_code == 503
