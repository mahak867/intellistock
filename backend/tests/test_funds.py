"""Mutual funds: AMFI NAV parsing, CAS conversion, and the /funds API (SQLite, fake AMFI)."""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core import database
from backend.data import amfi
from backend.models.db_models import Base, User
from backend.tools import cas as CAS

NAV_FILE = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Flexi Cap Fund)

Parag Parikh Mutual Fund

122639;INF879O01027;-;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;92.1234;05-Nov-2026
122640;INF879O01019;-;Parag Parikh Flexi Cap Fund - Regular Plan - Growth;85.5;05-Nov-2026
Open Ended Schemes(Index Funds)
120716;INF769K01DM9;-;UTI Nifty 50 Index Fund - Direct Plan - Growth;180.75;05-Nov-2026
999999;INF000000000;-;Closed Fund;N.A.;05-Nov-2026
"""

DETAILED = {"parse_warnings": [], "folios": [{"folio": "12345678 / 90", "amc": "PPFAS Mutual Fund", "schemes": [{
    "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "isin": "INF879O01027", "amfi": "122639", "close": "150.0",
    "valuation": {"date": "2026-10-31", "nav": "90.0", "value": "13500.0", "cost": "9000.0"},
    "transactions": [
        {"date": "2023-01-02", "type": "PURCHASE", "amount": "5000", "units": "100"},
        {"date": "2024-01-02", "type": "PURCHASE_SIP", "amount": "5000", "units": "75"},
        {"date": "2025-01-02", "type": "REDEMPTION", "amount": "-2000", "units": "-25"},
        {"date": "2025-02-02", "type": "STAMP_DUTY_TAX", "amount": "0.25", "units": None},
    ]}, {"scheme": "Old Closed Fund", "isin": "INF000000001", "amfi": "100001", "close": "0", "valuation": {"date": "2026-10-31", "nav": "10", "value": "0"}, "transactions": []}]}]}
NSDL = {"mutual_funds": [{"name": "UTI Nifty 50 Index Fund", "isin": "INF769K01DM9", "amfi": None, "balance": "40", "nav": "180", "value": "7200", "total_cost": "6000"}]}

ME, OTHER = "5f0c2a9e-3b7d-4c1e-9a2f-7d8e6b5a4c3d", "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"


NEW_FORMAT = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date\r
 \r
Open Ended Schemes(Children's Fund)\r
135762;INF846K01WO1;-;Axis Children's Fund;Direct Plan;Growth Option;30.5281;05-Nov-2026\r
135765;INF846K01WP8;-;Axis Children's Fund;Direct Plan;IDCW Option;28.1219;05-Nov-2026\r
"""


def test_amfi_parse_2026_format_with_plan_and_option():
    """The real file (checked on GitHub's runners, Nov 2026) gained Plan and Option columns."""
    d = amfi.parse(NEW_FORMAT)
    assert d["135762"].nav == 30.5281 and d["135762"].name == "Axis Children's Fund - Direct Plan - Growth Option"
    assert [n.code for n in amfi.search(d, "axis direct idcw")] == ["135765"]


def test_amfi_parse():
    d = amfi.parse(NAV_FILE)
    assert set(d) == {"122639", "122640", "120716"}  # N.A. NAV skipped, headers skipped
    assert d["122639"].nav == 92.1234 and d["122639"].date == date(2026, 11, 5) and d["122639"].isins == ("INF879O01027",)
    assert amfi.by_isin(d)["INF769K01DM9"].code == "120716"
    assert [n.code for n in amfi.search(d, "parag direct")] == ["122639"]
    with pytest.raises(ValueError):
        amfi.parse("Code|Name|NAV\n1|x|2\n")


def test_cas_conversion():
    rows, notes = CAS.holdings_from(DETAILED)
    pp = rows[0]
    assert pp["units"] == 150 and pp["invested"] == 9000 and pp["scheme_code"] == "122639"
    assert [t["amount"] for t in pp["transactions"]] == [-5000, -5000, 2000]  # taxes ignored
    rows, notes = CAS.holdings_from(NSDL)
    assert rows[0]["units"] == 40 and rows[0]["transactions"] == [] and "XIRR is not available" in notes[0]


def test_real_parser_rejects_a_non_cas_pdf():
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
    with pytest.raises(ValueError):
        CAS.read_pdf(pdf, "x")


@pytest.fixture
def api(tmp_path, monkeypatch):
    from backend.api.main import app
    from backend.api.routes.auth import get_current_user

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'f.db'}")

    async def setup():
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(eng, class_=AsyncSession)() as s:
            s.add_all([User(id=ME, email="me@example.com", full_name="m", hashed_password="x"), User(id=OTHER, email="o@example.com", full_name="o", hashed_password="x")])
            await s.commit()

    asyncio.run(setup())
    monkeypatch.setattr(database, "AsyncSessionFactory", async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False))
    parsed = amfi.parse(NAV_FILE)
    monkeypatch.setattr(amfi, "navs", lambda *a, **k: parsed)
    who = {"sub": ME}
    app.dependency_overrides[get_current_user] = lambda: who
    c = TestClient(app)
    c.who = who
    yield c
    app.dependency_overrides.clear()
    asyncio.run(eng.dispose())


def _upload(api, monkeypatch, cas_dict, password="pass"):
    def fake(data, pw):
        if pw != "pass":
            raise ValueError("Wrong password. CAS statements are usually locked with the password you chose when requesting them.")
        return cas_dict
    monkeypatch.setattr(CAS, "read_pdf", fake)
    return api.post("/api/v1/funds/import-cas", files={"file": ("cas.pdf", b"%PDF-1.7 fake", "application/pdf")}, data={"password": password})


def test_import_value_and_xirr(api, monkeypatch):
    r = _upload(api, monkeypatch, DETAILED)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1 and "not stored" in r.json()["message"]  # the fully redeemed fund is skipped
    j = api.get("/api/v1/funds").json()
    f = j["funds"][0]
    assert f["nav"] == 92.1234 and f["nav_source"] == "amfi" and f["value"] == round(150 * 92.1234, 2)
    assert f["xirr"] is not None and 0 < f["xirr"] < 100 and j["total"]["invested"] == 9000
    again = _upload(api, monkeypatch, DETAILED)  # re-import replaces, no duplicates
    assert again.status_code == 200 and len(api.get("/api/v1/funds").json()["funds"]) == 1


def test_import_errors(api, monkeypatch):
    assert _upload(api, monkeypatch, DETAILED, password="wrong").status_code == 422
    r = api.post("/api/v1/funds/import-cas", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}, data={"password": "p"})
    assert r.status_code == 422 and "not a PDF" in r.json()["detail"]
    r = api.post("/api/v1/funds/import-cas", files={"file": ("x.pdf", b"%PDF" + b"0" * (10 * 1024 * 1024 + 10), "application/pdf")}, data={"password": "p"})
    assert r.status_code == 413
    assert _upload(api, monkeypatch, {"folios": []}).status_code == 422


def test_manual_add_search_delete_and_privacy(api):
    assert api.get("/api/v1/funds/schemes?q=nifty").json()["schemes"][0]["scheme_code"] == "120716"
    r = api.post("/api/v1/funds", json={"scheme_code": "120716", "units": 40, "invested": 6000, "date": "2024-02-01"})
    assert r.status_code == 201, r.text
    assert api.post("/api/v1/funds", json={"scheme_code": "120716", "units": 1, "invested": 1, "date": "2024-02-01"}).status_code == 409
    assert api.post("/api/v1/funds", json={"scheme_code": "424242", "units": 1, "invested": 1, "date": "2024-02-01"}).status_code == 422
    assert api.post("/api/v1/funds", json={"scheme_code": "120716", "units": 1, "invested": 1, "date": "2099-01-01", "folio": "x"}).status_code == 422
    f = api.get("/api/v1/funds").json()["funds"][0]
    assert f["value"] == 40 * 180.75 and f["xirr"] is not None
    api.who["sub"] = OTHER
    assert api.get("/api/v1/funds").json()["funds"] == []
    assert api.delete(f"/api/v1/funds/{f['id']}").status_code == 404
    api.who["sub"] = ME
    assert api.delete(f"/api/v1/funds/{f['id']}").status_code == 204 and api.get("/api/v1/funds").json()["funds"] == []


def test_amfi_down_falls_back_to_statement_nav(api, monkeypatch):
    _upload(api, monkeypatch, DETAILED)

    def down(*a, **k):
        raise ConnectionError("x")
    monkeypatch.setattr(amfi, "navs", down)
    j = api.get("/api/v1/funds").json()
    assert j["funds"][0]["nav"] == 90.0 and j["funds"][0]["nav_source"] == "statement" and "unavailable" in j["nav_note"]
    assert api.get("/api/v1/funds/schemes?q=nifty").status_code == 502
