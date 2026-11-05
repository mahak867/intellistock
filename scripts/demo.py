"""Run IntelliStock on your own computer with one command. Needs only Python and Node.

    pip install -r requirements.txt
    python scripts/demo.py

It starts the API (SQLite file and in-memory cache instead of Postgres and Redis) and the web app, creates a demo
account with a sample watchlist and portfolio, and prints the address and login. Press Ctrl+C to stop.

Everything on screen uses PLACEHOLDER prices unless you have loaded NSE files (see README, "real data").
The demo database lives in ./data/demo.sqlite3. Delete it to start fresh.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "frontend-react"
EMAIL, PASSWORD, NAME = "demo@example.com", "Demo-Pass-2026!", "Demo User"
HOLDINGS = [("TCS", 10, 3400.0, "2025-02-10"), ("RELIANCE", 25, 1250.0, "2025-06-03"), ("INFY", 40, 1500.0, "2025-09-15")]
WATCH = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


def call(base: str, method: str, path: str, body=None, token: str | None = None, form: dict | None = None):
    data, headers = None, {}
    if form is not None:
        data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def wait_for(url: str, seconds: int, what: str, proc: subprocess.Popen | None = None) -> None:
    end = time.time() + seconds
    while time.time() < end:
        if proc is not None and proc.poll() is not None:
            sys.exit(f"{what} stopped while starting. Scroll up for the error.")
        try:
            with urllib.request.urlopen(url, timeout=3):
                return
        except Exception:
            time.sleep(1)
    sys.exit(f"{what} did not start within {seconds}s. Scroll up for the error.")


def seed(api: str) -> None:
    status, _ = call(api, "POST", "/auth/register", {"email": EMAIL, "password": PASSWORD, "full_name": NAME})
    if status not in (200, 201, 409):
        print(f"  note: could not create the demo account ({status}). If you ran the demo before, that is fine.")
    status, tok = call(api, "POST", "/auth/login", form={"username": EMAIL, "password": PASSWORD})
    if status != 200:
        sys.exit(f"Could not log in as the demo user ({status}): {tok}")
    token = tok["access_token"]
    _, have = call(api, "GET", "/users/portfolio", token=token)
    if not (have or {}).get("portfolio"):
        for t, q, p, d in HOLDINGS:
            call(api, "POST", "/users/portfolio", {"ticker": t, "quantity": q, "avg_buy_price": p, "buy_date": f"{d}T00:00:00"}, token=token)
    _, wl = call(api, "GET", "/stocks/watchlist", token=token)
    if not (wl or {}).get("watchlist"):
        for t in WATCH:
            call(api, "POST", "/stocks/watchlist", {"ticker": t}, token=token)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-port", type=int, default=8000)
    ap.add_argument("--web-port", type=int, default=3000)
    ap.add_argument("--rebuild", action="store_true", help="rebuild the web app even if a build exists")
    a = ap.parse_args()

    missing = []
    for mod in ("fastapi", "uvicorn", "aiosqlite", "fakeredis", "sqlalchemy"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        sys.exit(f"Missing Python packages: {', '.join(missing)}.\nRun: pip install -r requirements.txt")
    npm = shutil.which("npm")
    if not npm:
        sys.exit("Node.js is not installed. Install Node 20 or newer from https://nodejs.org and run this again.")

    api_base = f"http://localhost:{a.api_port}/api/v1"
    web_url = f"http://localhost:{a.web_port}"
    env = {
        **os.environ,
        "TF_CPP_MIN_LOG_LEVEL": "3", "DEMO_LITE": "1", "ENVIRONMENT": "development", "DEBUG": "false", "DATA_PROVIDER": os.environ.get("DATA_PROVIDER", "synthetic"),
        "SECRET_KEY": os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        # Required by the settings but unused in demo mode:
        "DATABASE_URL": "postgresql+asyncpg://demo:demo@localhost:5432/demo", "REDIS_URL": "redis://localhost:6379/0",
        "ALLOWED_ORIGINS": json.dumps([web_url, f"http://127.0.0.1:{a.web_port}"]),
    }
    web_env = {**os.environ, "NEXT_PUBLIC_API_BASE": api_base}
    web_env.pop("NEXT_PUBLIC_DEMO", None)

    if not (WEB / "node_modules").exists():
        print("Installing web dependencies (first run only, a few minutes)...")
        if subprocess.call([npm, "install", "--no-audit", "--no-fund"], cwd=WEB, env=web_env) != 0:
            sys.exit("npm install failed.")
    marker = WEB / ".next" / ".demo-api-base"
    if a.rebuild or not (WEB / ".next" / "BUILD_ID").exists() or not marker.exists() or marker.read_text() != api_base:
        print("Building the web app (first run only)...")
        if subprocess.call([npm, "run", "build"], cwd=WEB, env=web_env) != 0:
            sys.exit("Web build failed.")
        marker.write_text(api_base)

    procs: list[subprocess.Popen] = []
    try:
        print("Starting the API...")
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.api.main:app", "--port", str(a.api_port), "--log-level", "warning"], cwd=ROOT, env=env)
        procs.append(api)
        wait_for(f"{api_base}/health", 120, "The API", api)
        print("Creating the demo account and sample data...")
        seed(api_base)
        print("Starting the web app...")
        web = subprocess.Popen([npm, "run", "start", "--", "-p", str(a.web_port)], cwd=WEB, env=web_env)
        procs.append(web)
        wait_for(f"{web_url}/login", 60, "The web app", web)
        print(f"""
=====================================================================
  IntelliStock is running:  {web_url}

  Sign in with
    email     {EMAIL}
    password  {PASSWORD}

  Prices are PLACEHOLDERS (the app says so on screen). Press Ctrl+C to stop.
=====================================================================""")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("A process stopped; shutting down.")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
