"""Headlines and exchange announcements for a stock.

* News: Google News RSS search (free, no key), newest first.
* Announcements: NSE's corporate-announcements website API (unofficial; NSE blocks many cloud servers, so this can fail).
"""
from __future__ import annotations

import email.utils
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx

from backend.tools.corpactions import NSE_HOME, UA

GNEWS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
NSE_ANN = "https://www.nseindia.com/api/corporate-announcements"


def parse_rss(xml_text: str, limit: int = 20) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src = it.find("source")
        when = it.findtext("pubDate")
        try:
            ts = email.utils.parsedate_to_datetime(when).astimezone(timezone.utc).isoformat() if when else None
        except (TypeError, ValueError):
            ts = None
        if title and link.startswith("http"):
            out.append({"title": title, "url": link, "source": src.text.strip() if src is not None and src.text else None, "published": ts})
    out.sort(key=lambda r: r["published"] or "", reverse=True)
    return out[:limit]


def news(symbol: str, company: str | None = None, client: httpx.Client | None = None) -> list[dict]:
    q = f'"{company}"' if company else f"{symbol} NSE share"
    c = client or httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": UA})
    try:
        r = c.get(GNEWS.format(q=quote_plus(q)))
        r.raise_for_status()
        return parse_rss(r.text)
    finally:
        if client is None:
            c.close()


def announcements(symbol: str, client: httpx.Client | None = None, limit: int = 20) -> list[dict]:
    c = client or httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        c.get(NSE_HOME)
        r = c.get(NSE_ANN, params={"index": "equities", "symbol": symbol.upper()}, headers={"Referer": f"{NSE_HOME}/companies-listing/corporate-filings-announcements"})
        r.raise_for_status()
        rows = r.json()
        rows = rows if isinstance(rows, list) else rows.get("data", [])
    finally:
        if client is None:
            c.close()
    out = []
    for a in rows[:limit]:
        when = a.get("an_dt") or a.get("sort_date")
        try:
            ts = datetime.strptime(when, "%d-%b-%Y %H:%M:%S").isoformat() if when else None
        except ValueError:
            ts = when
        out.append({"title": a.get("desc") or a.get("subject"), "detail": (a.get("attchmntText") or "")[:500], "url": a.get("attchmntFile"), "published": ts})
    return out
