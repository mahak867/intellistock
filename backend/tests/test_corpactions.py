"""Corporate actions: parsing NSE descriptions and adjusting holdings."""
from datetime import date

import httpx
import pytest

from backend.tools import corpactions as CA


@pytest.mark.parametrize("subject,expected", [
    ("Dividend - Rs 10 Per Share", [{"kind": "dividend", "amount": 10.0}]),
    ("Interim Dividend - Rs 5.50 Per Share", [{"kind": "dividend", "amount": 5.5}]),
    ("Final Dividend - Rs 24 Per Share And Special Dividend - Rs 66 Per Share", [{"kind": "dividend", "amount": 90.0}]),
    ("Dividend - Re 1 Per Share", [{"kind": "dividend", "amount": 1.0}]),
    ("Bonus 1:1", [{"kind": "bonus", "ratio_new": 1.0, "ratio_old": 1.0}]),
    ("Bonus 3:2", [{"kind": "bonus", "ratio_new": 3.0, "ratio_old": 2.0}]),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", [{"kind": "split", "ratio_new": 10.0, "ratio_old": 2.0}]),
    ("Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- Per Share", [{"kind": "split", "ratio_new": 5.0, "ratio_old": 1.0}]),
    ("Annual General Meeting", []),
    ("Buy Back", []),
    ("Rights 1:5 @ Premium Rs 200/-", []),
])
def test_parse_nse_subjects(subject, expected):
    assert CA.parse_subject(subject) == expected


def test_split_bonus_and_dividends_adjust_in_order():
    acts = [
        {"kind": "dividend", "ex_date": date(2024, 6, 1), "amount": 10, "ratio_new": None, "ratio_old": None},
        {"kind": "split", "ex_date": date(2024, 9, 1), "amount": None, "ratio_new": 10, "ratio_old": 2},   # x5
        {"kind": "bonus", "ex_date": date(2025, 1, 1), "amount": None, "ratio_new": 1, "ratio_old": 1},   # x2
        {"kind": "dividend", "ex_date": date(2025, 6, 1), "amount": 2, "ratio_new": None, "ratio_old": None},
        {"kind": "dividend", "ex_date": date(2023, 1, 1), "amount": 99, "ratio_new": None, "ratio_old": None},  # before purchase
    ]
    r = CA.adjust(10, 1000.0, date(2024, 1, 15), acts)
    assert r["quantity"] == 100 and r["avg_price"] == 100.0  # cost unchanged: 10 x 1000 = 100 x 100
    assert [d["cash"] for d in r["dividends"]] == [100.0, 200.0] and r["dividends_total"] == 300.0


def test_bought_on_ex_date_is_not_entitled():
    r = CA.adjust(10, 100, date(2025, 1, 1), [{"kind": "bonus", "ex_date": date(2025, 1, 1), "amount": None, "ratio_new": 1, "ratio_old": 1}])
    assert r["quantity"] == 10


def test_from_nse_rows_and_fetch_with_mock():
    rows = [{"symbol": "TCS", "subject": "Interim Dividend - Rs 11 Per Share", "exDate": "17-Oct-2025"},
            {"symbol": "TCS", "subject": "Annual General Meeting", "exDate": "01-Jun-2025"},
            {"symbol": "TCS", "subject": "Dividend - Rs 5 Per Share", "exDate": "not a date"}]

    def handler(req: httpx.Request):
        if req.url.path == "/":
            return httpx.Response(200, text="<html></html>", headers={"set-cookie": "nsit=abc; Path=/"})
        assert req.url.params["symbol"] == "TCS"
        return httpx.Response(200, json=rows)

    got = CA.fetch_nse("tcs", httpx.Client(transport=httpx.MockTransport(handler)))
    assert got == [{"ticker": "TCS", "ex_date": date(2025, 10, 17), "source_text": rows[0]["subject"], "kind": "dividend", "amount": 11.0}]
