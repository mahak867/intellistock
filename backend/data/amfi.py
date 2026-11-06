"""Mutual fund NAVs from AMFI (free, published daily): https://portal.amfiindia.com/spages/NAVAll.txt

Format: section headers and blank lines, then rows
    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
AMFI has changed this file before, so parsing checks the header and skips rows it cannot read.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime

import httpx

URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
TTL_SECONDS = 6 * 3600


@dataclass(frozen=True)
class Nav:
    code: str
    name: str
    isins: tuple[str, ...]
    nav: float
    date: date


def parse(text: str) -> dict[str, Nav]:
    """Columns are found by header name: AMFI added Plan and Option columns in 2026, which broke fixed positions."""
    lines = text.splitlines()
    head = next((l for l in lines if l.lower().startswith("scheme code")), None)
    if head is None or "net asset value" not in head.lower():
        raise ValueError("AMFI NAV file format changed: header line not found.")
    cols = [c.strip().lower() for c in head.split(";")]

    def col(*names):
        return next((i for i, c in enumerate(cols) for n in names if c.startswith(n)), None)

    i_code, i_name, i_nav, i_date = col("scheme code"), col("scheme name"), col("net asset value"), col("date")
    i_isin1, i_isin2 = col("isin div payout", "isin growth"), col("isin div reinvestment")
    i_plan, i_opt = col("plan"), col("option")
    if None in (i_code, i_name, i_nav, i_date):
        raise ValueError(f"AMFI NAV file format changed: columns are {cols}.")
    out: dict[str, Nav] = {}
    for l in lines:
        parts = [p.strip() for p in l.split(";")]
        if len(parts) != len(cols) or not parts[i_code].isdigit():
            continue
        try:
            nav = float(parts[i_nav])
            d = datetime.strptime(parts[i_date], "%d-%b-%Y").date()
        except ValueError:
            continue  # "N.A." NAVs and odd rows
        isins = tuple(x for x in (parts[i] for i in (i_isin1, i_isin2) if i is not None) if x and len(x) == 12)
        name = parts[i_name]
        extra = [parts[i] for i in (i_plan, i_opt) if i is not None and parts[i] and parts[i].lower() not in name.lower()]
        out[parts[i_code]] = Nav(parts[i_code], " - ".join([name, *extra]), isins, nav, d)
    if len(out) < 100 and len(lines) > 200:
        raise ValueError("AMFI NAV file format changed: almost no rows could be read.")
    return out


_cache: dict = {"at": 0.0, "navs": None}
_lock = threading.Lock()


def navs(client: httpx.Client | None = None, force: bool = False) -> dict[str, Nav]:
    with _lock:
        if not force and _cache["navs"] is not None and time.time() - _cache["at"] < TTL_SECONDS:
            return _cache["navs"]
        c = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "IntelliStock/1.0"})
        try:
            r = c.get(URL)
            r.raise_for_status()
            data = parse(r.text)
        finally:
            if client is None:
                c.close()
        _cache.update(at=time.time(), navs=data)
        return data


def by_isin(data: dict[str, Nav]) -> dict[str, Nav]:
    return {i: n for n in data.values() for i in n.isins}


def search(data: dict[str, Nav], q: str, limit: int = 20) -> list[Nav]:
    words = [w for w in q.lower().split() if w]
    hits = [n for n in data.values() if all(w in n.name.lower() for w in words)]
    return sorted(hits, key=lambda n: (len(n.name), n.name))[:limit]
