"""Yahoo fundamentals mapping, the live fundamentals screener, and news parsing (all with mocked sources)."""
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.data import fundamentals_feed as FF
from backend.data import news as N

INFO = {"longName": "Tata Consultancy Services Limited", "sector": "Technology", "currentPrice": 3480.0, "trailingPE": 25.4,
        "priceToBook": 12.1, "returnOnEquity": 0.512, "debtToEquity": 9.5, "profitMargins": 0.19, "revenueGrowth": 0.06,
        "marketCap": 12_600_000_000_000, "dividendYield": 1.8, "heldPercentInsiders": 0.72, "beta": 0.5}


def test_from_info_units():
    r = FF.from_info("tcs", INFO)
    assert r["symbol"] == "TCS" and r["roe"] == 51.2 and r["debt_equity"] == 0.095 and r["market_cap_cr"] == 1_260_000.0
    assert r["insider_holding"] == 72.0 and r["profit_cagr_3y"] is None and r["source"] == "Yahoo Finance"
    assert FF.from_info("x", {"trailingPE": float("nan")})["pe"] is None


def test_live_screener(monkeypatch):
    rows = [FF.from_info("TCS", INFO), FF.from_info("BADCO", {**INFO, "longName": "Bad Co", "returnOnEquity": 0.03, "debtToEquity": 250}),
            FF.from_info("NODEBT", {k: v for k, v in INFO.items() if k != "debtToEquity"})]
    monkeypatch.setattr(FF, "fetch_many", lambda syms, workers=8: (rows, ["MISSING"]))
    c = TestClient(app)
    r = c.post("/api/v1/tools/screener/fundamentals/live", json={"universe": "custom", "tickers": ["TCS", "BADCO", "NODEBT", "MISSING"],
                                                                 "filters": [{"field": "roe", "min": 15}, {"field": "debt_equity", "max": 1}]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert [x["symbol"] for x in j["rows"]] == ["TCS"] and j["rows"][0]["name"].startswith("Tata")
    assert j["left_out_for_missing_data"]["debt_equity"] == 1 and j["missing"] == ["MISSING"] and "Yahoo" in j["source"]
    monkeypatch.setattr(FF, "fetch_many", lambda syms, workers=8: ([], syms))
    assert c.post("/api/v1/tools/screener/fundamentals/live", json={"universe": "nifty50"}).status_code == 502
    assert c.post("/api/v1/tools/screener/fundamentals/live", json={"universe": "custom", "tickers": ["bad sym!"]}).status_code == 422


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>TCS wins deal</title><link>https://example.com/a</link><pubDate>Thu, 05 Nov 2026 10:00:00 GMT</pubDate><source url="x">Mint</source></item>
<item><title>TCS Q2 results</title><link>https://example.com/b</link><pubDate>Fri, 06 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title>bad link</title><link>javascript:alert(1)</link></item>
</channel></rss>"""


def test_parse_rss_newest_first_and_safe_links():
    r = N.parse_rss(RSS)
    assert [x["title"] for x in r] == ["TCS Q2 results", "TCS wins deal"] and r[1]["source"] == "Mint"


def test_news_endpoint_survives_source_failures(monkeypatch):
    monkeypatch.setattr(FF, "fetch_one", lambda t, exchange="NSE": {"name": "Tata Consultancy Services"})
    monkeypatch.setattr(N, "news", lambda s, company=None: N.parse_rss(RSS))

    def blocked(s):
        raise ConnectionError("blocked")
    monkeypatch.setattr(N, "announcements", blocked)
    j = TestClient(app).get("/api/v1/market/news/TCS").json()
    assert len(j["news"]) == 2 and j["announcements"] == [] and "NSE announcements unavailable" in j["errors"][0]
    assert TestClient(app).get("/api/v1/market/news/bad%20sym").status_code == 422


def test_fundamentals_endpoint(monkeypatch):
    monkeypatch.setattr(FF, "fetch_one", lambda t, exchange="NSE": FF.from_info(t, INFO))
    assert TestClient(app).get("/api/v1/market/fundamentals/tcs").json()["pe"] == 25.4

    def none(t, exchange="NSE"):
        raise LookupError("Yahoo Finance has no fundamentals for ZZZ.")
    monkeypatch.setattr(FF, "fetch_one", none)
    assert TestClient(app).get("/api/v1/market/fundamentals/ZZZ").status_code == 404
