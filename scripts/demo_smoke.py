"""Check a running `python scripts/demo.py`: API, sign-in, the seeded data, the main pages, and (optionally) a phone browser.

    python scripts/demo.py            # in one terminal
    python scripts/demo_smoke.py      # in another; add --browser webkit|chromium to also drive pages in a phone browser
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API, WEB = "http://localhost:8000/api/v1", "http://localhost:3000"
EMAIL, PASSWORD = "demo@example.com", "Demo-Pass-2026!"
fails: list[str] = []


def check(name: str, ok: bool, extra="") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""), flush=True)
    if not ok:
        fails.append(name)


def call(method, path, body=None, token=None, form=None):
    data, h = None, {}
    if form is not None:
        data, h["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(API + path, data=data, method=method, headers=h), timeout=120) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]


def wait(url: str, seconds: int) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=5)
            return True
        except Exception:
            time.sleep(3)
    return False


def browser(kind: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = getattr(p, kind).launch()
        dev = p.devices["iPhone 14"] if kind == "webkit" else p.devices["Pixel 7"]
        ctx = b.new_context(**dev)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(WEB + "/login")
        pg.fill("#email", EMAIL)
        pg.fill("#password", PASSWORD)
        pg.click("button[type=submit]")
        pg.wait_for_url("**/dashboard", timeout=60000)
        check(f"{kind}: signed in on a phone", True)
        check(f"{kind}: bottom navigation shown", pg.get_by_role("button", name="More").is_visible())
        pg.wait_for_load_state("networkidle", timeout=60000)
        for path, text in (("/portfolio", "Portfolio"), ("/alerts", "Your alerts"), ("/tools", "Position size"), ("/broker", "Zerodha"), ("/help", "Questions")):
            pg.goto(WEB + path)
            pg.wait_for_selector(f"text={text}", timeout=60000)
            pg.wait_for_load_state("networkidle", timeout=60000)  # let the page finish its requests, as a person reading it would
            w = pg.evaluate("[document.documentElement.scrollWidth, innerWidth]")
            check(f"{kind}: {path} renders without sideways scroll", w[0] <= w[1], w)
        pg.goto(WEB + "/tools?tool=fscreen")
        pg.click("text=Calculate")
        pg.wait_for_selector("text=stocks match", timeout=60000)
        check(f"{kind}: a tool runs", True)
        pg.goto(WEB + "/funds")
        pg.wait_for_selector("text=Import a CAS statement", timeout=60000)
        w = pg.evaluate("[document.documentElement.scrollWidth, innerWidth]")
        check(f"{kind}: /funds renders without sideways scroll", w[0] <= w[1], w)
        pg.goto(WEB + "/portfolio")
        pg.wait_for_selector("text=Dividends, bonuses and splits", timeout=60000)
        check(f"{kind}: portfolio shows corporate actions", True)
        pg.goto(WEB + "/research?ticker=TCS")
        pg.wait_for_selector("text=Exchange announcements", timeout=60000)
        pg.wait_for_load_state("networkidle", timeout=90000)
        w = pg.evaluate("[document.documentElement.scrollWidth, innerWidth]")
        check(f"{kind}: /research renders without sideways scroll", w[0] <= w[1], w)
        pg.goto(WEB + "/tools?tool=taxlots")
        pg.click("text=Calculate")
        pg.wait_for_selector("text=long-term gain you can still book", timeout=60000)
        check(f"{kind}: tax lots and harvesting runs", True)
        check(f"{kind}: no page errors", not errors, errors[:2])
        b.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=900, help="seconds to wait for the demo to come up")
    ap.add_argument("--browser", choices=["webkit", "chromium"])
    a = ap.parse_args()
    check("API is up", wait(API + "/health", a.wait))
    check("web app is up", wait(WEB + "/login", a.wait))
    s, tok = call("POST", "/auth/login", form={"username": EMAIL, "password": PASSWORD})
    check("demo login", s == 200, s)
    if s != 200:
        return 1
    t = tok["access_token"]
    s, pf = call("GET", "/users/portfolio", token=t)
    check("seeded portfolio has 3 holdings", s == 200 and len(pf.get("portfolio", [])) == 3, (s, pf))
    s, wl = call("GET", "/stocks/watchlist", token=t)
    check("seeded watchlist has 5 stocks", s == 200 and len(wl.get("watchlist", [])) == 5, (s, wl))
    s, fc = call("GET", "/market/forecast/TCS?horizon=10", token=t)
    check("forecast answers with a range", s == 200 and fc and len(fc.get("fan", [])) == 10, s)
    s, a1 = call("POST", "/users/alerts", {"ticker": "TCS", "alert_type": "price_above", "price_target": 1}, token=t)
    s, chk = call("POST", "/users/alerts/check", token=t)
    check("alert check fires (placeholder-labelled)", s == 200 and chk["fired"] and chk["fired"][0]["message"].startswith("[placeholder"), (s, chk))
    s, al = call("GET", "/users/alerts", token=t)
    for r in (al or {}).get("alerts", []):
        call("DELETE", f"/users/alerts/{r['id']}", token=t)
    s, _ = call("POST", "/tools/costs", {"segment": "equity_delivery", "buy_price": 100, "sell_price": 110, "qty": 10})
    check("a tool endpoint answers", s == 200, s)
    book = "trade_date,symbol,trade_type,quantity,price\n2024-01-10,TCS,buy,10,3000\n2025-09-15,TCS,sell,4,3800\n"
    s, tl = call("POST", "/tools/tax/lots", {"csv": book, "prices": {"TCS": 4000}, "as_of": "2026-01-15"})
    check("tax lots: FIFO gain and harvesting headroom", s == 200 and tl["realised"][0]["gain"] == 3200 and tl["harvest"]["headroom_left"] == 121800, (s, tl if s != 200 else tl["harvest"]))
    s, ca = call("POST", "/users/corporate-actions", {"ticker": "TCS", "kind": "bonus", "ex_date": "2025-06-02", "ratio_new": 1, "ratio_old": 1}, token=t)
    s2, pf2 = call("GET", "/users/portfolio", token=t)
    tcs = next((x for x in (pf2 or {}).get("portfolio", []) if x["ticker"] == "TCS"), {})
    check("corporate action doubles shares on a 1:1 bonus", s == 201 and tcs.get("quantity") == 2 * tcs.get("raw_quantity", -1), (s, tcs))
    if s == 201:
        call("DELETE", f"/users/corporate-actions/{ca['id']}", token=t)
    s, perf = call("GET", "/users/portfolio/performance", token=t)
    check("portfolio performance answers", s == 200 and len(perf["holdings"]) == 3, s)
    s, sch = call("GET", "/funds/schemes?q=nifty%2050%20index", token=t)
    if s == 502:
        print("SKIP mutual fund search: AMFI not reachable from this machine")
    else:
        check("AMFI scheme search", s == 200 and len(sch["schemes"]) > 0, s)
        if s == 200:
            code = sch["schemes"][0]["scheme_code"]
            s, add = call("POST", "/funds", {"scheme_code": code, "units": 10, "invested": 1000, "date": "2024-01-02"}, token=t)
            s2, fv = call("GET", "/funds", token=t)
            check("mutual fund added and valued at AMFI NAV", s == 201 and fv["funds"][0]["nav_source"] == "amfi" and fv["funds"][0]["value"] > 0, (s, s2))
            if s == 201:
                call("DELETE", f"/funds/{add['id']}", token=t)
    s, fu = call("GET", "/market/fundamentals/TCS", token=t)
    if s == 502:
        print("SKIP fundamentals: Yahoo not reachable from this machine")
    else:
        check("Yahoo fundamentals for TCS", s == 200 and fu.get("pe"), (s, fu))
    s, nw = call("GET", "/market/news/TCS", token=t)
    check("news endpoint answers", s == 200, s)
    s, wl2 = call("POST", "/stocks/watchlist", {"ticker": "SBIN", "list_name": "Banks"}, token=t)
    check("named watchlist", s == 201, s)
    s, fd = call("POST", "/assets", {"kind": "fd", "name": "Smoke FD", "amount": 100000, "rate": 7, "start_date": "2025-01-01"}, token=t)
    s2, nw = call("GET", "/assets", token=t)
    check("deposit added and counted in net worth", s == 201 and s2 == 200 and nw["net_worth"]["other"] > 100000, (s, s2))
    if s == 201:
        call("DELETE", f"/assets/{fd['id']}", token=t)
    s, bs = call("GET", "/broker/status", token=t)
    check("broker status answers (not connected)", s == 200 and bs["connected"] is False, (s, bs))
    if a.browser:
        browser(a.browser)
    print("\nFAILED: " + (", ".join(fails) if fails else "none"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
