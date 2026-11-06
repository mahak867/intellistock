"""Screenshots of the main pages with sample data, against a running scripts/demo.py.  python scripts/feature_screens.py OUT_DIR"""
import sys, json, urllib.request, urllib.parse
from playwright.sync_api import sync_playwright
O=sys.argv[1]; W="http://localhost:3000"; A="http://localhost:8000/api/v1"
def call(m,p,b=None,t=None,form=None):
    h={}; d=None
    if form: d=urllib.parse.urlencode(form).encode(); h["Content-Type"]="application/x-www-form-urlencoded"
    elif b is not None: d=json.dumps(b).encode(); h["Content-Type"]="application/json"
    if t: h["Authorization"]="Bearer "+t
    try: return json.load(urllib.request.urlopen(urllib.request.Request(A+p,data=d,method=m,headers=h)))
    except Exception as e: return None
t=call("POST","/auth/login",form={"username":"demo@example.com","password":"Demo-Pass-2026!"})["access_token"]
call("POST","/users/portfolio",{"ticker":"ITC","quantity":100,"avg_buy_price":400,"buy_date":"2023-03-01T00:00:00","account":"Mom"},t)
call("POST","/users/corporate-actions",{"ticker":"TCS","kind":"dividend","ex_date":"2025-07-16","amount":11},t)
call("POST","/users/corporate-actions",{"ticker":"RELIANCE","kind":"bonus","ex_date":"2025-10-28","ratio_new":1,"ratio_old":1},t)
for s,l in (("HDFCBANK","Banks"),("ICICIBANK","Banks"),("SBIN","Banks")): call("POST","/stocks/watchlist",{"ticker":s,"list_name":l},t)
call("POST","/users/alerts",{"ticker":"TCS","alert_type":"price_above","price_target":1},t); call("POST","/users/alerts/check",None,t)
with sync_playwright() as p:
    b=p.chromium.launch()
    for name,ctx in (("desk",dict(viewport={"width":1440,"height":900},device_scale_factor=2)),("phone",dict(**p.devices["iPhone 14"]))):
        c=b.new_context(**ctx); pg=c.new_page()
        pg.goto(W+"/login"); pg.fill("#email","demo@example.com"); pg.fill("#password","Demo-Pass-2026!"); pg.click("button[type=submit]"); pg.wait_for_url("**/dashboard")
        pages=[("dashboard","/dashboard",None),("portfolio","/portfolio","text=Dividends, bonuses and splits"),("funds","/funds","text=Import a CAS statement"),
               ("research","/research?ticker=TCS","text=Exchange announcements"),("taxlots","/tools?tool=taxlots",None),("broker","/broker","text=Zerodha"),("alerts","/alerts","text=Your alerts"),("help","/help","text=Questions")]
        if name=="phone": pages=[pages[0],pages[1],pages[4],pages[6]]
        for n,path,wait in pages:
            pg.goto(W+path)
            if wait: pg.wait_for_selector(wait,timeout=60000)
            if n=="taxlots": pg.click("text=Calculate"); pg.wait_for_selector("text=long-term gain you can still book",timeout=60000)
            pg.wait_for_timeout(2500)
            pg.screenshot(path=f"{O}/{name}-{n}.png", full_page=(name=="desk"))
        c.close()
    b.close()
