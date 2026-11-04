"""Screenshot the running app, and refuse to call placeholder data real.

    python scripts/capture_screens.py --base http://localhost:3000 --out screenshots

Needs: pip install playwright && playwright install chromium. Start the API and the React app first
(frontend-react: NEXT_PUBLIC_DEMO=1 npm run dev, or build and start). Each file is saved with the data
source the page itself reported; anything on placeholder or fixture data is saved as PLACEHOLDER-... so
it cannot be mistaken for real market data.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

TOOLS = ["Position size", "Trade costs", "Trade journal", "Option price and Greeks", "Payoff builder", "Open interest and max pain",
         "Daily loss limit", "Pre-trade checklist", "Expiry dates", "Screener", "Backtester", "Portfolio allocation", "Portfolio risk",
         "Your real return (XIRR)", "SIP calculator", "Goal planner", "Rebalancing", "Quality score", "Announcement digest", "Capital gains estimate"]
DATA_PAGES = {"Screener", "Backtester", "Portfolio risk"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:3000")
    ap.add_argument("--out", default="screenshots")
    ap.add_argument("--email", default=os.environ.get("CAPTURE_EMAIL"), help="login for a server that requires one (or set CAPTURE_EMAIL)")
    ap.add_argument("--password", default=os.environ.get("CAPTURE_PASSWORD"), help="or set CAPTURE_PASSWORD")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1300, "height": 900})

        def save(name: str, text: str, data: bool):
            fake = data and bool(re.search(r"placeholder|fixture", text, re.I))
            f = out / (("PLACEHOLDER-" if fake else "") + name + ".png")
            pg.screenshot(path=str(f), full_page=True)
            src = re.search(r"(NSE end-of-day prices as of [\d-]+|Local data store[^.]*|Placeholder prices[^.]*|Test fixture[^.]*)", text)
            print(f"{f.name:55} {src.group(1) if src else ''}")

        if a.email and a.password:
            pg.goto(a.base + "/login")
            pg.fill("#email", a.email)
            pg.fill("#password", a.password)
            pg.get_by_role("button", name="Sign in").click()
            pg.wait_for_timeout(3500)
        pg.goto(a.base + "/dashboard")
        pg.wait_for_timeout(2500)
        if "/login" in pg.url:
            print("The app sent us to the login page. Pass --email and --password (or set CAPTURE_EMAIL and CAPTURE_PASSWORD).")
            b.close()
            return 2
        for path, name in (("/dashboard", "dashboard"), ("/predictions", "forecast")):
            pg.goto(a.base + path)
            pg.wait_for_timeout(4000)
            save(name, pg.inner_text("body"), True)
        pg.goto(a.base + "/tools")
        pg.wait_for_timeout(2500)
        for i, t in enumerate(TOOLS, 1):
            pg.get_by_role("button", name=t, exact=True).click()
            pg.wait_for_timeout(400)
            if t == "Pre-trade checklist":
                for cb in pg.locator("input[type=checkbox]").all()[:4]:
                    cb.check()
            btn = pg.get_by_role("button", name="Calculate")
            if btn.count():
                btn.click()
            pg.wait_for_timeout(2500 if t in DATA_PAGES else 800)
            save(f"tools-{i:02d}-{slug(t)}", pg.locator("section[aria-live]").inner_text(), t in DATA_PAGES)
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
