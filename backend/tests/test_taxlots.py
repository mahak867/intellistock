"""Tax lots and LTCG harvesting from a Zerodha-style tradebook."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.tools import taxlots as TL

BOOK = """symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
TCS,INE467B01029,2024-01-10,NSE,EQ,EQ,buy,false,10,3000,1,1,2024-01-10T10:00:00
TCS,INE467B01029,2025-08-01,NSE,EQ,EQ,buy,false,5,3500,2,2,2025-08-01T10:00:00
TCS,INE467B01029,2025-09-15,NSE,EQ,EQ,sell,false,4,3800,3,3,2025-09-15T10:00:00
INFY,INE009A01021,2025-10-01,NSE,EQ,EQ,buy,false,20,1500,4,4,2025-10-01T10:00:00
INFY,INE009A01021,2025-10-01,NSE,EQ,EQ,sell,false,20,1550,5,5,2025-10-01T14:00:00
RELIANCE,INE002A01018,2025-06-01,NSE,EQ,EQ,sell,false,5,1300,6,6,2025-06-01T10:00:00
NIFTY25DECFUT,,2025-11-01,NFO,FO,,buy,false,75,24000,7,7,2025-11-01T10:00:00
HDFCBANK,INE040A01034,2017-06-01,NSE,EQ,EQ,buy,false,100,800,8,8,2017-06-01T10:00:00
HDFCBANK,INE040A01034,2025-11-01,NSE,EQ,EQ,sell,false,50,1700,9,9,2025-11-01T10:00:00
"""
FMV = BOOK.replace("order_execution_time\n", "order_execution_time,fmv_31jan2018\n").replace("2017-06-01T10:00:00", "2017-06-01T10:00:00,900")
FMV = "\n".join(l + ("," if l and not l.endswith(",900") and not l.startswith("symbol") else "") for l in FMV.splitlines()) + "\n"
AS_OF = date(2026, 1, 15)
PRICES = {"TCS": 4000.0, "HDFCBANK": 1800.0}


def test_fifo_lots_gains_and_warnings():
    r = TL.report(FMV, PRICES, AS_OF)
    g = {(x["symbol"], x["term"]): x for x in r["realised"]}
    assert g[("TCS", "long")]["gain"] == 3200 and g[("TCS", "long")]["buy_date"] == "2024-01-10"  # FIFO: oldest lot sold
    assert g[("HDFCBANK", "long")]["gain"] == 40000  # grandfathered cost max(800, min(900, 1700)) = 900
    assert not any(x["symbol"] == "INFY" for x in r["realised"])  # same-day buy+sell = intraday, left out
    w = " ".join(r["warnings"])
    assert "intraday" in w and "RELIANCE: sold 5" in w and "other segments" in w
    lots = {(l["symbol"], l["buy_date"]): l for l in r["open_lots"]}
    assert lots[("TCS", "2024-01-10")]["qty"] == 6 and lots[("TCS", "2024-01-10")]["long_term"]
    assert not lots[("TCS", "2025-08-01")]["long_term"] and lots[("TCS", "2025-08-01")]["long_term_from"] == "2026-08-02"
    fy = r["realised_by_year"]["2025-26"]
    assert fy["ltcg"] == 43200 and fy["taxable_ltcg"] == 0 and fy["estimated_tax_with_cess"] == 0


def test_harvest_follows_fifo_and_headroom():
    h = TL.report(FMV, PRICES, AS_OF)["harvest"]
    assert h["financial_year"] == "2025-26" and h["exemption_used_so_far"] == 43200 and h["headroom_left"] == 81800
    plan = {p["symbol"]: p for p in h["suggested_sales"]}
    assert plan["HDFCBANK"]["sell_qty"] == 50 and plan["HDFCBANK"]["long_term_gain_booked"] == 45000
    assert plan["TCS"]["sell_qty"] == 6  # stops before the short-term lot bought 2025-08-01
    assert h["headroom_after_suggestions"] == 81800 - 45000 - 6000
    assert all(p["worth_it"] for p in plan.values())


def test_harvest_respects_a_small_headroom():
    book = "date,symbol,side,qty,price\n2023-01-02,ITC,buy,1000,200\n2025-06-02,ITC,sell,500,400\n"  # LT gain 100000 already this FY
    h = TL.report(book, {"ITC": 400.0}, date(2026, 1, 15))["harvest"]
    assert h["headroom_left"] == 25000 and h["suggested_sales"][0]["sell_qty"] == 125  # 25000 / 200 per share


def test_without_fmv_grandfathering_is_flagged():
    r = TL.report(BOOK, PRICES, AS_OF)
    assert any("31 Jan 2018" in w for w in r["warnings"])
    assert next(x for x in r["realised"] if x["symbol"] == "HDFCBANK")["gain"] == 45000  # cost 800: overstated, flagged


def test_old_years_get_no_tax_figure():
    book = "date,symbol,side,qty,price\n2022-01-03,ITC,buy,10,200\n2024-03-01,ITC,sell,10,400\n"
    y = TL.report(book, {}, AS_OF)["realised_by_year"]["2023-24"]
    assert y["estimated_tax_with_cess"] is None and y["ltcg"] == 2000


@pytest.mark.parametrize("bad", ["", "a,b\n1,2\n", "date,symbol,side,qty,price\n2025-01-01,TCS,hold,1,1\n",
                                 "date,symbol,side,qty,price\n2025-01-01,TCS,buy,-1,1\n", "date,symbol,side,qty,price\nnotadate,TCS,buy,1,1\n",
                                 "date,symbol,side,qty,price\n2025-01-01,TCS,buy,nan,1\n"])
def test_bad_tradebooks_are_clear_errors(bad):
    with pytest.raises(ValueError):
        TL.report(bad, {}, AS_OF)


def test_dd_mm_yyyy_dates():
    fills, _ = TL.parse_tradebook("Trade Date,Symbol,Trade Type,Quantity,Price\n15-09-2025,TCS,BUY,1,3000\n")
    assert fills[0]["date"] == date(2025, 9, 15) and fills[0]["side"] == "buy"


def test_api_endpoint():
    c = TestClient(app)
    r = c.post("/api/v1/tools/tax/lots", json={"csv": FMV, "prices": PRICES, "as_of": "2026-01-15"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["harvest"]["headroom_left"] == 81800 and j["price_sources"]["TCS"] == "you"
    assert c.post("/api/v1/tools/tax/lots", json={"csv": "a,b\n1,2"}).status_code == 422
