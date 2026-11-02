import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from backend.data import providers, store
from backend.data.bhavcopy import StaleFile, download_day, parse_udiff
from backend.data.prices import build_ohlcv

HEADER = "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,TtlTradgVol"


def udiff(d: str, rows: list[tuple], spaced=True) -> bytes:
    sep = ", " if spaced else ","
    lines = [HEADER.replace(",", sep)]
    for sym, series, o, h, l, c, pc, v in rows:
        lines.append(sep.join([d, d, "CM", "NSE", "STK", "1", "INE000", sym, series, str(o), str(h), str(l), str(c), str(c), str(pc), str(v)]))
    return "\n".join(lines).encode()


def zipped(b: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("BhavCopy.csv", b)
    return buf.getvalue()


def test_parse_handles_zip_and_spaces():
    raw = zipped(udiff("2026-10-30", [("TCS", "EQ", 100, 105, 99, 104, 100, 5000)]))
    df = parse_udiff(raw, date(2026, 10, 30))
    r = df.iloc[0]
    assert r.symbol == "TCS" and r.series == "EQ" and r.close == 104 and r.prev_close == 100 and r.volume == 5000
    assert str(r.date.date()) == "2026-10-30"


def test_parse_rejects_wrong_day_and_bad_layout():
    raw = udiff("2026-10-30", [("TCS", "EQ", 100, 105, 99, 104, 100, 5000)])
    with pytest.raises(StaleFile):
        parse_udiff(raw, date(2026, 10, 31))
    with pytest.raises(ValueError, match="unexpected file layout"):
        parse_udiff(b"a,b\n1,2")


def rows_for(days, closes, sym="ABC", prevs=None):
    prevs = prevs or [None] + closes[:-1]
    out = []
    for d, c, p in zip(days, closes, prevs):
        out.append({"date": pd.Timestamp(d), "symbol": sym, "series": "EQ", "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                    "prev_close": p if p is not None else c, "volume": 1000.0})
    return pd.DataFrame(out)


DAYS = pd.bdate_range("2026-01-05", periods=6)


def test_split_is_adjusted_so_the_series_is_continuous():
    # 2-for-1 split on day 4: raw close halves, the exchange's previous close for that day is already halved.
    closes = [100, 101, 102, 51, 52, 53]
    prevs = [None, 100, 101, 51, 51, 52]
    df, q = build_ohlcv(rows_for(DAYS, closes, prevs=prevs), "ABC", today=date(2026, 1, 13))
    assert len(q["corporate_actions_adjusted"]) == 1 and q["corporate_actions_adjusted"][0]["factor"] == pytest.approx(0.5)
    assert df["close"].iloc[0] == pytest.approx(50.0) and df["close"].iloc[2] == pytest.approx(51.0)
    assert df["close"].pct_change().abs().max() < 0.03
    assert df["volume"].iloc[0] == pytest.approx(2000.0)


def test_small_difference_after_missing_day_is_not_treated_as_corporate_action():
    rows = rows_for(DAYS, [100, 101, 102, 103, 104, 105])
    # another stock proves day 3 was a trading day, ABC just lacks it, and the exchange previous close differs by 2%
    other = rows_for(DAYS, [10] * 6, sym="OTH")
    rows = rows[rows["date"] != DAYS[2]].copy()
    rows.loc[rows["date"] == DAYS[3], "prev_close"] = 102 * 1.0  # 103 close vs prev 102 = ratio vs our prior close 101
    all_rows = pd.concat([rows, other])
    df, q = build_ohlcv(all_rows, "ABC", today=date(2026, 1, 13))
    assert q["corporate_actions_adjusted"] == []
    assert any("missing" in i for i in q["issues"])


def test_bad_rows_dropped_and_staleness_flagged():
    r = rows_for(DAYS, [100, 101, 102, 103, 104, 105])
    r.loc[2, "high"] = 50.0  # high below low
    df, q = build_ohlcv(r, "ABC", today=date(2026, 3, 1))
    assert len(df) == 5 and any("dropped" in i for i in q["issues"]) and any("days old" in i for i in q["issues"])


def test_unknown_symbol_raises():
    with pytest.raises(KeyError):
        build_ohlcv(rows_for(DAYS, [1] * 6), "NOPE")


class FakeResp:
    def __init__(self, code, content=b""):
        self.status_code, self.content = code, content

    def raise_for_status(self):
        raise RuntimeError(self.status_code)


class FakeClient:
    def __init__(self, by_date):
        self.by_date, self.calls = by_date, []

    def get(self, url):
        key = url.split("_")[-3]  # YYYYMMDD
        self.calls.append(key)
        return self.by_date.get(key, FakeResp(404))


def test_download_caches_and_skips_holidays(tmp_path):
    d = date(2026, 10, 12)
    body = zipped(udiff("2026-10-12", [("TCS", "EQ", 100, 105, 99, 104, 100, 5000)]))
    c = FakeClient({"20261012": FakeResp(200, body)})
    assert len(download_day(d, c, tmp_path, delay=0)) == 1
    assert len(download_day(d, c, tmp_path, delay=0)) == 1 and c.calls == ["20261012"]  # second call came from cache
    assert download_day(date(2026, 10, 13), c, tmp_path, delay=0) is None
    assert download_day(date(2026, 10, 13), c, tmp_path, delay=0) is None
    assert c.calls.count("20261013") == 1  # the 404 was remembered (old enough to be a holiday)


def test_stale_file_is_not_cached(tmp_path):
    body = zipped(udiff("2026-10-09", [("TCS", "EQ", 100, 105, 99, 104, 100, 5000)]))
    c = FakeClient({"20261012": FakeResp(200, body)})
    with pytest.raises(StaleFile):
        download_day(date(2026, 10, 12), c, tmp_path, delay=0)
    assert not list((tmp_path / "raw").glob("*.zip"))


def test_fetch_range_builds_store_and_provider_reads_it(tmp_path, monkeypatch):
    days = [d for d in store.weekdays(date(2026, 10, 5), date(2026, 10, 9))]
    by = {f"{d:%Y%m%d}": FakeResp(200, zipped(udiff(f"{d:%Y-%m-%d}", [("TCS", "EQ", 100 + i, 105 + i, 99, 104 + i, 100 + i, 5000)]))) for i, d in enumerate(days)}
    res = store.fetch_range(days[0], days[-1], tmp_path, FakeClient(by), delay=0)
    assert res["downloaded_or_cached_days"] == 5 and res["store_rows"] == 5 and not res["failed"]
    monkeypatch.setattr(providers.settings, "DATA_PROVIDER", "nse", raising=False)
    monkeypatch.setattr(providers.settings, "DATA_DIR", str(tmp_path), raising=False)
    st = providers.status()
    assert st["real_data"] is True and st["symbols"] == 1 and st["last"] == "2026-10-09"
    with pytest.raises(providers.NoData, match="Only 5 days"):
        providers.get_prices("TCS")
    with pytest.raises(providers.NoData, match="No data for ZZZ"):
        providers.get_prices("ZZZ")


def test_synthetic_provider_is_labelled(monkeypatch):
    monkeypatch.setattr(providers.settings, "DATA_PROVIDER", "synthetic", raising=False)
    p = providers.get_prices("TCS", 300)
    assert p.synthetic and len(p.df) == 300 and providers.status()["real_data"] is False


def test_missing_store_is_an_error_not_fake_data(tmp_path, monkeypatch):
    monkeypatch.setattr(providers.settings, "DATA_PROVIDER", "nse", raising=False)
    monkeypatch.setattr(providers.settings, "DATA_DIR", str(tmp_path / "empty"), raising=False)
    with pytest.raises(providers.NoData, match="fetch_data"):
        providers.get_prices("TCS")
