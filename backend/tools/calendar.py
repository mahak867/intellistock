"""Event calendar: computed F&O expiries plus user/vendor-supplied events.

NSE derivatives expire on Tuesday (from 1 Sep 2025, per SEBI/NSE circular 103/2025); BSE on
Thursday. Monthly = last Tuesday of the month. If that day is a holiday the expiry moves to
the previous trading day. Holidays must be supplied: they are published yearly by the exchange.
Results, dividends and RBI policy dates are NOT computed: load them from a vendor or CSV.
"""
from __future__ import annotations

import calendar as cal
import csv
import io
from datetime import date, timedelta


def _prev_trading_day(d: date, holidays: set[date]) -> date:
    while d.weekday() >= 5 or d in holidays:
        d -= timedelta(days=1)
    return d


def monthly_expiry(year: int, month: int, holidays: set[date] | None = None, weekday: int = 1) -> date:
    """weekday: Tuesday=1 (NSE), Thursday=3 (BSE)."""
    last = date(year, month, cal.monthrange(year, month)[1])
    d = last - timedelta(days=(last.weekday() - weekday) % 7)
    return _prev_trading_day(d, holidays or set())


def weekly_expiries(start: date, end: date, holidays: set[date] | None = None, weekday: int = 1) -> list[date]:
    out, d = [], start + timedelta(days=(weekday - start.weekday()) % 7)
    hol = holidays or set()
    while d <= end:
        out.append(_prev_trading_day(d, hol))
        d += timedelta(days=7)
    return out


def parse_events_csv(text: str) -> list[dict]:
    """Columns: date (YYYY-MM-DD), symbol, type, note"""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        out.append({"date": date.fromisoformat(row["date"].strip()), "symbol": row["symbol"].strip().upper(),
                    "type": row["type"].strip(), "note": (row.get("note") or "").strip()})
    return sorted(out, key=lambda e: e["date"])


def upcoming(events: list[dict], today: date, days: int = 14, symbols: set[str] | None = None) -> list[dict]:
    end = today + timedelta(days=days)
    return [e for e in events if today <= e["date"] <= end and (not symbols or e["symbol"] in symbols)]
