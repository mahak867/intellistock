"""Fundamentals screener: reads Screener.in-style CSVs, filters honestly, never invents data."""
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.tools import fundscreen as F

CSV = """Name,CMP Rs.,P/E,Mar Cap Rs.Cr.,ROCE %,ROE %,Debt / Eq,Prom. Hold. %,Profit Var 3Yrs %
SAMPLE-A,100,12.5,"5,000",22,18,0.1,60,15
SAMPLE-B,200,45,900,8,6,1.8,30,-2
SAMPLE-C,50,-,100,30,25,,70,40
"""


@pytest.fixture(scope="module")
def c():
    yield TestClient(app)


def test_parse_recognises_screener_headers_and_numbers():
    df, info = F.parse(CSV)
    assert set(["pe", "roe", "roce", "debt_equity", "promoter_holding", "profit_cagr_3y", "market_cap_cr"]) <= set(df.columns)
    assert df.loc[df.symbol == "SAMPLE-A", "market_cap_cr"].iloc[0] == 5000.0  # thousands separator
    assert df.loc[df.symbol == "SAMPLE-C", "pe"].isna().all()  # "-" is missing, not zero


def test_filters_and_missing_data_are_counted_not_guessed():
    out = F.screen(CSV, [{"field": "debt_equity", "max": 0.5}])
    assert [r["symbol"] for r in out["rows"]] == ["SAMPLE-A"]  # C has no debt figure, so it is left out
    assert out["left_out_for_missing_data"]["debt_equity"] == 1


def test_filter_on_column_the_file_lacks_matches_nothing():
    out = F.screen(CSV, [{"field": "pledge_pct", "max": 5}])
    assert out["matched"] == 0 and out["filters_on_missing_columns"] == ["pledge_pct"]


def test_sorting_and_limit():
    assert F.screen(CSV, [], "quality")["rows"][0]["quality_grade"] in ("strong", "average", "weak")
    assert [r["symbol"] for r in F.screen(CSV, [{"field": "roe", "min": 5}], "roe", 2)["rows"]] == ["SAMPLE-C", "SAMPLE-A"]
    assert [r["symbol"] for r in F.screen(CSV, [{"field": "roe", "min": 5}], "pe", 5)["rows"]][0] == "SAMPLE-A"  # lower PE first


@pytest.mark.parametrize("bad", ["", "a,b\n1,2\n", "Name,Foo\nX,1\n", "ROE,PE\n10,10\n"])
def test_unusable_csv_is_a_clear_error(bad):
    with pytest.raises(ValueError):
        F.screen(bad, [])


def test_min_above_max_rejected():
    with pytest.raises(ValueError):
        F.screen(CSV, [{"field": "roe", "min": 20, "max": 10}])


def test_api_roundtrip_and_validation(c):
    r = c.post("/api/v1/tools/screener/fundamentals", json={"csv": CSV, "filters": [{"field": "roe", "min": 15}]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["matched"] == 2 and "uploaded" in j["note"]
    for body in [{"csv": CSV, "filters": [{"field": "nope", "min": 1}]},
                 {"csv": CSV, "filters": [{"field": "roe", "min": 1e30}]},
                 {"csv": CSV, "sort": "nope"},
                 {"csv": CSV, "limit": 0},
                 {"csv": "", "filters": []},
                 {"csv": CSV, "filters": [{"field": "roe", "min": 1}] * 13}]:
        assert c.post("/api/v1/tools/screener/fundamentals", json=body).status_code == 422, body
    assert c.post("/api/v1/tools/screener/fundamentals", content='{"csv": "x", "filters": [{"field": "roe", "min": NaN}]}',
                  headers={"content-type": "application/json"}).status_code == 422
