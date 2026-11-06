"""Bringing in assets: bank statements, broker holdings exports, NSDL/CDSL statements, deposits, and net worth."""
import asyncio
import io
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core import database
from backend.data import amfi, providers
from backend.models.db_models import Base, User
from backend.tools import assets as AS
from backend.tools import cas as CAS

SBI = """State Bank of India
Account Name :,MR MAHAK
Account Number :,00000031234567890
Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance
01 Oct 2026,01 Oct 2026,BY TRANSFER,,,"50,000.00","1,20,500.00"
15 Oct 2026,15 Oct 2026,UPI/ZOMATO,,450.00,,"1,20,050.00"
31 Oct 2026,31 Oct 2026,ATM WDL,,"5,000.00",,"1,15,050.00"
"""
HDFC_NEWEST_FIRST = """HDFC BANK Ltd. Statement of account
Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
05/11/26,SALARY,,05/11/26,,90000.00,250000.00
01/11/26,RENT,,01/11/26,40000.00,,160000.00
"""
ZERODHA = "Instrument,Qty.,Avg. cost,LTP,Cur. val,P&L,Net chg.,Day chg.\nTCS,10,3300.5,3480,34800,1795,5.4,0.2\nINFY,25,1450,1500,37500,1250,3.4,-0.1\nGOLDBEES-BE,5,60,70,350,50,1,0\n"


def _xlsx(rows):
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False, header=False, engine="openpyxl")
    return buf.getvalue()


def test_bank_balance_oldest_first_csv():
    r = AS.bank_balance(SBI.encode(), "sbi.csv")
    assert r["balance"] == 115050.0 and r["as_of"] == date(2026, 10, 31) and r["bank"] in ("SBI", "State Bank") and r["account_hint"] == "xx7890"


def test_bank_balance_newest_first_csv():
    r = AS.bank_balance(HDFC_NEWEST_FIRST.encode(), "hdfc.csv")
    assert r["balance"] == 250000.0 and r["as_of"] == date(2026, 11, 5) and r["bank"] == "HDFC"


def test_bank_balance_xlsx_with_logo_rows():
    data = _xlsx([["ICICI Bank"], [""], ["S No.", "Value Date", "Transaction Date", "Cheque Number", "Transaction Remarks", "Withdrawal Amount (INR )", "Deposit Amount (INR )", "Balance (INR )"],
                  ["1", "02/10/2026", "02/10/2026", "", "NEFT", "", "1000", "21000"], ["2", "20/10/2026", "20/10/2026", "", "POS", "500", "", "20500"]])
    assert AS.bank_balance(data, "icici.xlsx")["balance"] == 20500.0


@pytest.mark.parametrize("bad", [b"", b"just text without a table", b"Date,Amount\n1,2\n"])
def test_bank_statement_without_balances_is_an_error(bad):
    with pytest.raises(ValueError):
        AS.bank_balance(bad, "x.csv")


def test_broker_exports():
    z = AS.broker_holdings(ZERODHA.encode(), "holdings.csv")
    assert z == [{"symbol": "TCS", "qty": 10.0, "avg_price": 3300.5}, {"symbol": "INFY", "qty": 25.0, "avg_price": 1450.0}, {"symbol": "GOLDBEES", "qty": 5.0, "avg_price": 60.0}]
    groww = _xlsx([["Holdings statement"], ["Client Code", "X123"], [""], ["Stock Name", "ISIN", "Quantity", "Average buy price", "Buy value"],
                   ["RELIANCE", "INE002A01018", "12", "1250.5", "15006"]])
    assert AS.broker_holdings(groww, "groww.xlsx") == [{"symbol": "RELIANCE", "qty": 12.0, "avg_price": 1250.5}]


def test_fd_value_quarterly_compounding_stops_at_maturity():
    v = AS.fd_value(100000, 7.0, date(2024, 1, 1), date(2025, 1, 1), date(2026, 6, 1))
    assert abs(v - 100000 * (1 + 0.07 / 4) ** (4 * 366 / 365)) < 1


NSDL = {"accounts": [{"name": "Zerodha", "type": "CDSL", "dp_id": "12081600", "client_id": "01234567", "folios": 0, "balance": "0",
                      "owners": [], "equities": [{"name": "TATA CONSULTANCY SERV LT", "isin": "INE467B01029", "num_shares": "10", "price": "3480", "value": "34800", "symbol": "TCS"},
                                                 {"name": "UNKNOWN LTD", "isin": "INE000X01010", "num_shares": "3", "price": "10", "value": "30", "symbol": None}],
                      "mutual_funds": [{"name": "UTI Nifty 50 Index Fund", "isin": "INF769K01DM9", "amfi": "120716", "balance": "40", "nav": "180", "value": "7200", "total_cost": "6000"}],
                      "bonds": [{"name": "GOI SGB 2031", "isin": "IN0020230085", "num_bonds": "10", "value": "70000"}]}],
        "nps": {"pran": "1100XXXX", "value": "250000", "schemes": []}}


def test_depository_assets_and_cas_funds():
    a = AS.depository_assets(NSDL)
    assert [e["symbol"] for e in a["equities"]] == ["TCS", None] and a["bonds"][0]["value"] == 70000 and a["nps"]["value"] == 250000
    rows, notes = CAS.holdings_from(NSDL)
    assert rows[0]["scheme_code"] == "120716" and rows[0]["units"] == 40  # funds inside demat accounts are found


ME = "5f0c2a9e-3b7d-4c1e-9a2f-7d8e6b5a4c3d"


@pytest.fixture
def api(tmp_path, monkeypatch):
    from backend.api.main import app
    from backend.api.routes.auth import get_current_user

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")

    async def setup():
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(eng, class_=AsyncSession)() as s:
            s.add(User(id=ME, email="me@example.com", full_name="m", hashed_password="x"))
            await s.commit()

    asyncio.run(setup())
    monkeypatch.setattr(database, "AsyncSessionFactory", async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False))
    monkeypatch.setattr(amfi, "navs", lambda *a, **k: {})

    def prices(sym, days=260):
        df = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0}, index=pd.bdate_range(end="2026-10-30", periods=5))
        return providers.Prices(df, "nse", None)
    monkeypatch.setattr(providers, "get_prices", prices)
    app.dependency_overrides[get_current_user] = lambda: {"sub": ME}
    yield TestClient(app)
    app.dependency_overrides.clear()
    asyncio.run(eng.dispose())


def test_imports_and_net_worth(api, monkeypatch):
    r = api.post("/api/v1/assets/import-bank", files={"file": ("sbi.csv", SBI.encode(), "text/csv")}, data={"account": "Me"})
    assert r.status_code == 200, r.text
    again = api.post("/api/v1/assets/import-bank", files={"file": ("sbi.csv", SBI.encode(), "text/csv")}, data={"account": "Me"})
    assert again.json()["id"] == r.json()["id"]  # same account updates, not duplicates
    r = api.post("/api/v1/assets/import-holdings", files={"file": ("holdings.csv", ZERODHA.encode(), "text/csv")}, data={"account": "Me"})
    assert r.status_code == 200 and r.json()["added"] == 3, r.text
    assert api.post("/api/v1/assets", json={"kind": "fd", "name": "SBI FD", "amount": 100000, "rate": 7, "start_date": "2025-01-01", "maturity_date": "2027-01-01"}).status_code == 201
    assert api.post("/api/v1/assets", json={"kind": "fd", "name": "No rate", "amount": 1}).status_code == 422
    monkeypatch.setattr(CAS, "read_pdf", lambda data, pw: NSDL)
    r = api.post("/api/v1/assets/import-depository", files={"file": ("cas.pdf", b"%PDF-1.7 x", "application/pdf")}, data={"password": "p", "account": "Mom"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["stocks_added"] == 1 and j["funds"] == 1 and j["other_assets"] == 2 and j["skipped_stocks"] == ["UNKNOWN LTD"]
    nw = api.get("/api/v1/assets").json()["net_worth"]
    people = {p["account"]: p for p in nw["by_person"]}
    assert people["Me"]["stocks"] == 4000 and people["Me"]["other"] > 115050 + 100000  # 40 shares at 100; FD has grown
    assert people["Mom"]["stocks"] == 1000 and people["Mom"]["funds"] == 7200 and people["Mom"]["other"] == 320000
    assert nw["total"] == round(sum(p["total"] for p in nw["by_person"]), 2) and nw["by_kind"]["bank"] == 115050


def test_cams_statement_sent_to_the_wrong_button(api, monkeypatch):
    monkeypatch.setattr(CAS, "read_pdf", lambda data, pw: {"folios": []})
    r = api.post("/api/v1/assets/import-depository", files={"file": ("cas.pdf", b"%PDF-1.7 x", "application/pdf")}, data={"password": "p"})
    assert r.status_code == 422 and "Funds page" in r.json()["detail"]
