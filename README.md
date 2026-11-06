# 📈 IntelliStock
### NSE/BSE Market Intelligence Platform

> **LSTM-powered Indian stock market forecasting with BUY/SELL/HOLD signal generation, deployed on cloud infrastructure with enterprise-grade security.**

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![TensorFlow](https://img.shields.io/badge/TensorFlow-2.20-orange)](https://tensorflow.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 🎯 Overview

IntelliStock is a full-stack, production-ready market intelligence platform built for the Indian equity market (NSE/BSE). It combines deep learning (Bidirectional LSTM with Bahdanau Attention) with classical technical analysis to show likely price ranges, risk and costs for Indian stocks.

**Status, honestly:** a working full-stack app with a real API, authentication, 241 automated tests and a React UI. Prices are placeholders until you load NSE end-of-day files (`scripts/fetch_data.py`, see `LICENSING.md`); NSE's current equity and index files are checked against the parser by the `Live data checks` workflow (last run: PASS on the 5 Nov 2026 files). It is not deployed anywhere, has no users, and the price-direction forecast has no demonstrated edge, so the app shows ranges and risk, not buy/sell calls you should trade on.

---

## ✨ Key Features

| Category | Features |
|---|---|
| **ML/AI** | BiLSTM + Attention, GRU baseline, 30+ technical features, NIFTY50 macro input |
| **Signals** | Legacy BUY/SELL/HOLD endpoints from the old LSTM. The new screens show price ranges instead, because the direction forecast showed no edge in testing (see Measured accuracy) |
| **Alerts** | Price-above, price-below and unusually-wide-day alerts, checked on the latest end-of-day close every 30 minutes (Celery beat). Telegram delivery uses your own bot token and has only been tested against a mock, not a live bot. Nothing is sent off-app while prices are placeholders or unlicensed |
| **Fundamentals screener** | Filter and rank stocks on a CSV you export (for example from Screener.in): P/E, ROE, ROCE, debt/equity, promoter holding, growth. IntelliStock ships no fundamentals data |
| **Broker (Zerodha)** | Connect your own Kite Connect app: live holdings, import into your portfolio, live prices (needs Kite's market-data add-on), and limit orders. Each order is previewed and confirmed within 2 minutes, a confirmation sends at most one order, prices more than 20% from the last price or orders over ₹10 lakh are refused as likely typos, and every order is logged. Keys and tokens are encrypted at rest. Tested against a simulated Kite API built from Zerodha's documented formats, not a live account |
| **Mutual funds** | Import a CAS statement (CAMS, KFintech, NSDL, CDSL) or add funds by hand; valued at AMFI's daily NAV; XIRR from statement transactions. The CAS reader (casparser) has only been tested with synthetic data, not a real statement |
| **Dividends, bonuses, splits** | Record them per holding (or pick from NSE's list; NSE's website blocks cloud servers, so lookup may fail there) and quantities, average price and returns include them |
| **Return vs NIFTY 50** | XIRR per holding and overall, compared with the same cash flows in NIFTY 50; holdings under a year show plain return |
| **Tax lots and harvesting** | FIFO lots from your tradebook, gains by financial year, and how much long-term gain fits in this year's Rs 1.25 lakh exemption |
| **Mobile** | Phone layout with a bottom bar, installable from the browser (Add to Home Screen). No offline mode on purpose. Checked in an emulated 390px browser, not on a real phone |
| **API** | FastAPI, JWT auth, refresh tokens, rate limiting, Redis caching |
| **Security** | BCrypt passwords, token revocation, HTTPS-only headers, CORS, rate limits |
| **Data** | NSE holiday calendar, yfinance with retry, parquet caching, 5Y historical |
| **Monitoring** | Prometheus metrics, Grafana dashboards, Sentry error tracking, OpenTelemetry |
| **Deployment** | Docker + Compose (`infra/docker/`); GitHub Actions CI runs the backend tests (`.github/workflows/ci.yml`); no automated cloud deploy yet |
| **Database** | PostgreSQL + SQLAlchemy async, Alembic migrations, Redis cache |
| **Testing** | 241 automated tests (pytest) — tools, data layer, API, backtest, security |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      IntelliStock                           │
├──────────────┬──────────────────────────┬───────────────────┤
│  Streamlit   │      FastAPI Backend     │   Celery Workers  │
│  Dashboard   │   (4 uvicorn workers)    │  (retrain, alerts)│
└──────┬───────┴──────────┬───────────────┴─────────┬─────────┘
       │                  │                          │
       ▼                  ▼                          ▼
  ┌─────────┐    ┌──────────────────┐      ┌────────────────┐
  │  Redis  │    │   PostgreSQL     │      │  Cloud Storage │
  │ (cache) │    │ (users, signals, │      │ (S3/GCS/Azure) │
  │ (JWT)   │    │  pred logs, etc) │      │ (model weights)│
  └─────────┘    └──────────────────┘      └────────────────┘
       │
  ┌────▼──────────────────────────────────────────────────┐
  │               ML Pipeline                            │
  │  yfinance → Holiday fill → Split → Feature Eng →    │
  │  BiLSTM+Attention → Evaluate → Signal → Cache       │
  └───────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker + Docker Compose
- PostgreSQL 16
- Redis 7

### 1. Clone & setup
```bash
git clone https://github.com/mahak867/intellistock.git
cd intellistock
cp .env.example .env
# Edit .env — fill in SECRET_KEY, DB password, Redis password
```

### 2. Generate secret key
```bash
python -c "import secrets; print(secrets.token_hex(32))"
# Paste into .env → SECRET_KEY
```

### 3. Start all services
```bash
docker-compose up -d
```

Services available:
| Service | URL |
|---|---|
| API (FastAPI) | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| Dashboard (Streamlit) | http://localhost:8501 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Flower (Celery) | http://localhost:5555 |

### 4. Train the model
```bash
# Train on RELIANCE (default), uploads model artefacts
python train.py --ticker RELIANCE --epochs 100

# Train on multiple tickers
python train.py --ticker TCS --epochs 100 --upload
```

### 5. Run tests
```bash
pytest backend/tests/ ml/tests/ --cov=backend --cov=ml -v
```

---

## 📊 Model Architecture

### Primary: Bidirectional LSTM + Bahdanau Attention

```
Input (60, 31)
    ↓
BiLSTM (128 units) + BatchNorm
    ↓
BiLSTM (64 units) + BatchNorm
    ↓
BahdanauAttention (64 units)   ← learns which time steps matter most
    ↓
Dropout(0.3)
    ↓
Dense(64, relu) + BatchNorm + Dropout
    ↓
Dense(32, relu) + BatchNorm + Dropout
    ↓
Dense(1)  → predicted Close price
```

### Features (31 total)
- **Price**: OHLCV, Log Returns, HL Ratio, OC Ratio
- **Trend**: SMA20, SMA50, EMA12, EMA26, price-MA ratios, golden/death cross
- **Momentum**: RSI (with overbought/oversold flags), MACD, MACD Signal, MACD Histogram
- **Volatility**: Bollinger Bands (width + position), ATR, 5d/20d rolling volatility
- **Volume**: OBV (normalised), Volume/SMA20 ratio
- **Macro**: NIFTY50 daily return (India-specific market co-movement)
- **Calendar**: IsHoliday flag (NSE market calendar)

### Key Engineering Decisions
| Decision | Reason |
|---|---|
| Scaler fitted on train only | Prevents data leakage into val/test |
| Indicators computed before split | Then scaler applied per split |
| Huber loss instead of MSE | Robust to price spike outliers |
| Gradient clipping (norm=1.0) | Prevents LSTM exploding gradients |
| `shuffle=False` in training | Never shuffle time series data |
| BiLSTM over vanilla LSTM | Captures both forward and backward temporal patterns |
| Attention layer | Model learns to weight recent market events appropriately |

---

## 🔒 Security

- **Passwords**: bcrypt with salt (passlib)
- **JWT**: Access tokens (30 min) + Refresh tokens (7 days, stored in Redis)
- **Token Revocation**: Logout blocklists access tokens in Redis until natural expiry
- **Rate Limiting**: 60 req/min per IP (slowapi + Redis), 10 req/min for batch
- **HTTPS**: HSTS header enforced in production (`max-age=31536000`)
- **Headers**: X-Frame-Options DENY, X-Content-Type-Options nosniff, XSS protection
- **Secrets**: All credentials from environment variables — zero hardcoded secrets
- **File Upload**: MIME type + size validation on all uploads
- **Admin Routes**: Role-based access control on sensitive endpoints

---

## 🌐 API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/register` | ❌ | Create account |
| POST | `/api/v1/auth/login` | ❌ | Get JWT tokens |
| POST | `/api/v1/auth/refresh` | ❌ | Rotate access token |
| POST | `/api/v1/auth/logout` | ✅ | Revoke tokens |
| GET  | `/api/v1/auth/me` | ✅ | Current user |
| GET  | `/api/v1/predictions/{ticker}` | ✅ | Price forecast |
| GET  | `/api/v1/predictions/{ticker}/signal` | ✅ | BUY/SELL/HOLD |
| POST | `/api/v1/predictions/batch` | ✅ | Up to 10 tickers |
| GET  | `/api/v1/predictions/{ticker}/history` | ✅ | Accuracy log |
| GET  | `/api/v1/stocks/{ticker}/ohlcv` | ✅ | Historical OHLCV |
| GET  | `/api/v1/stocks/{ticker}/indicators` | ✅ | Latest indicators |
| GET  | `/api/v1/stocks/nifty50` | ✅ | NIFTY50 tickers |
| GET  | `/api/v1/health` | ❌ | Liveness probe |
| GET  | `/api/v1/health/ready` | ❌ | Readiness probe |
| GET  | `/metrics` | ❌ | Prometheus metrics |

---

## ▶️ Try it on your computer (one command)

Needs Python 3.12 and Node 20+. No Postgres, Redis or Docker.

```bash
pip install -r requirements.txt
python scripts/demo.py
```

The first run installs and builds the web app (a few minutes). Then open http://localhost:3000 and sign in with `demo@example.com` / `Demo-Pass-2026!`. The demo uses a SQLite file (`data/demo.sqlite3`) and an in-memory cache, comes with a sample watchlist and portfolio, and shows **placeholder prices** (the app says so on screen). `DEMO_LITE` is refused outside `ENVIRONMENT=development`. Press Ctrl+C to stop.

## 📏 Measured accuracy (real NSE prices)

`python scripts/evaluate_real.py --dir <folder of CSVs>` runs the app's own walk-forward test (train on the past, predict forward, never peek) on a folder of daily price files and prints a scorecard. On 48 large-cap NSE stocks, 2016 to 2026 (a public GitHub dataset; it has no licence, so it is not included here):

| Test | 5 days | 10 days | 20 days |
|---|---|---|---|
| Direction hit rate (always-up baseline) | 50.6% (53.1%) | 50.9% (54.5%) | 50.8% (56.4%) |
| Stocks passing the edge test (luck alone gives about 1) | 0 of 48 | 0 of 48 | 0 of 48 |
| Volatility forecast beats the naive baseline | 44 of 48 | 34 of 48 | 31 of 48 |

The 80% price range held 84.6% of the time on newer data at 10 days (72% to 92% by stock; quantiles fitted on the older half, scored on the newer half). Reading: **the direction forecast has no demonstrated edge, so the app does not show Buy or Sell; the volatility range is the part that works.** Many stocks were tested, so a couple of "wins" would be expected by luck alone. Only 10-day coverage was re-measured with the holdout method. Prices are used as the dataset provides them; a few jumps over 25% in a day (mostly March 2020) are real moves, but unadjusted splits cannot be ruled out.

## Alerts

Create alerts on the **Alerts** page. A Celery beat task checks them every `ALERT_CHECK_MINUTES` (default 30) against the latest end-of-day close; prices are never live. To send them to Telegram, create a bot with @BotFather, set `TELEGRAM_BOT_TOKEN`, and each user saves their own chat id on the Alerts page. Delivery code is tested against a mock only. While prices are placeholders or unlicensed, alerts are labelled and shown in the app only.

## Broker (Zerodha Kite Connect)

1. Create an app at developers.kite.trade with your own Zerodha account. Set its Redirect URL to `https://<your IntelliStock site>/broker/callback`.
2. To place orders, add the server's static IP to your Kite developer profile (SEBI's retail-API rules from April 2026; Zerodha rejects orders from other IPs).
3. In IntelliStock open **Broker**, paste the API key and secret, and log in with Zerodha. Sessions end at 6 AM IST each day, so you log in once per trading day.

Once connected: holdings and live prices come from your account, the portfolio shows live P&L, and price alerts use the live price and can be sent to Telegram (it is your own data feed). Orders are LIMIT, DAY, delivery (CNC) or intraday (MIS), one per confirmation. Set `BROKER_ORDERS_ENABLED=false` to allow holdings and prices only. IntelliStock is not a broker or a SEBI-registered adviser.

## 🗄️ Database migrations

Development creates tables automatically. Anywhere else, create them with Alembic before the API starts (the API Docker image does this on boot):

```bash
alembic upgrade head                                   # apply
alembic check                                          # fails if the models have drifted from the migrations
alembic revision --autogenerate -m "describe change"   # after changing backend/models/db_models.py
```

## ☁️ Cloud Deployment

### GCP Cloud Run (recommended)
```bash
gcloud run deploy intellistock-api \
  --image gcr.io/PROJECT_ID/intellistock-api:latest \
  --region asia-south1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars ENVIRONMENT=production
```

### AWS ECS / Fargate
See `infra/terraform/` for full Terraform configuration.

### Environment Variables for Production
Set via GCP Secret Manager / AWS Secrets Manager — never in plaintext.

---

## 📁 Project Structure

```
intellistock/
├── backend/
│   ├── api/
│   │   ├── main.py              # FastAPI app factory
│   │   └── routes/
│   │       ├── auth.py          # JWT auth endpoints
│   │       ├── predictions.py   # ML inference endpoints
│   │       ├── stocks.py        # Market data endpoints
│   │       ├── users.py         # User management
│   │       └── health.py        # Liveness + readiness probes
│   ├── core/
│   │   ├── config.py            # Pydantic settings (env validation)
│   │   ├── database.py          # Async SQLAlchemy engine
│   │   └── redis_client.py      # Async Redis pool
│   ├── models/
│   │   └── db_models.py         # SQLAlchemy ORM models
│   ├── services/                # Business logic layer
│   └── tests/
│       └── test_suite.py        # Unit + integration tests
├── ml/
│   ├── data/
│   │   └── pipeline.py          # yfinance fetch, NSE calendar, splitting
│   ├── features/
│   │   └── engineer.py          # Zero-leakage feature engineering
│   └── models/
│       └── lstm.py              # BiLSTM+Attention, GRU, training loop
├── frontend/
│   └── app.py                   # Streamlit dashboard
├── infra/
│   ├── docker/
│   │   ├── Dockerfile.api       # Multi-stage production image
│   │   └── migrations/          # Alembic schema migrations (alembic.ini at the repo root)
├── .github/workflows/
│   └── ci.yml                   # GitHub Actions: backend tests
├── train.py                     # Model training CLI
├── docker-compose.yml           # Full local dev stack
├── requirements.txt             # Pinned dependencies
└── .env.example                 # Environment template
```

---

## 📈 Results

| Model | RMSE (₹) | MAE (₹) | MAPE | Directional Acc |
|---|---|---|---|---|
| GRU Baseline | 195.06 | 181.84 | 9.34% | 57.0% |
| BiLSTM + Attention | 467.32 | 433.91 | 22.13% | 43.0% |

*Development-run results on a synthetic random-walk dataset used to validate the pipeline end-to-end (chronological split, leakage-safe scaling, training, evaluation) independent of any live market outcome — not yet validated against real NSE data. Reported as measured: the GRU baseline outperformed the attention model on this run, which is discussed honestly in the [research paper](docs/) rather than omitted. A walk-forward backtest of the resulting signals (long/short, 10 bps transaction cost) returned -15.04% against a +17.50% buy-and-hold benchmark over the same window — see the backtesting engine in `ml/backtest/engine.py`. Re-running `python train.py --ticker <TICKER>` with live internet access against real NSE data is the direct next step and requires no code changes.*

---

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`pytest --cov=backend --cov=ml`)
4. Commit your changes (`git commit -m 'feat: add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

---

## 🖥️ Frontends

Two independent dashboards ship in this repo, both talking to the same backend API — pick either, or run both side by side:

- **`frontend/`** — the original Streamlit dashboard. Install its dependencies **separately** from the backend's, in their own virtualenv: `pip install -r requirements-dashboard.txt`. This is a separate file from `requirements.txt` on purpose — Streamlit's dependency chain conflicts with the backend's pinned FastAPI version in one shared environment (see the comment at the top of `requirements-dashboard.txt`).
- **`frontend-react/`** — a React/Next.js dashboard built on real [ReUI](https://github.com/keenthemes/reui) components. See `frontend-react/README.md` for setup.

## ⚠️ Known Issues / Honest Limitations

- Model performance numbers in this README are from a synthetic-data development run used to validate the pipeline (see [Results](#-results)) — not yet run against live NSE data.
- CI (`.github/workflows/ci.yml`) installs `requirements.txt` and runs `pytest backend/tests/`. It was added after an earlier broken workflow was removed; check the Actions tab for its current status. There is no automated deploy (Cloud Run or otherwise) yet.
- Celery: `backend/core/celery_app.py` runs alert checks every `ALERT_CHECK_MINUTES` and a daily retrain (`RETRAIN_TICKERS`, default `RELIANCE`). Both tasks were run end to end through a real worker, Redis and Postgres on real NSE prices. Training reads the local NSE store when `DATA_PROVIDER` is `nse`/`local` (or `python train.py --data-source store`), otherwise Yahoo Finance. Retrained models are saved locally; wiring them to the model registry is not done.
- Docker: CI builds the API image and boots it against Postgres and Redis, and brings up the whole `docker-compose.yml` stack (API, worker, scheduler, Flower, web app, Streamlit, Prometheus, Grafana), checks each service answers, and runs a Celery task through the worker.
- Live data: the `Live data checks` workflow (manual and weekly) runs on GitHub's runners because NSE and Yahoo are reachable there: NSE format check, a one-week real NSE download, and a Yahoo fetch. It found and confirmed fixes for two real breakages (an outdated yfinance, and a calendar alignment bug that returned 0 rows).
- Demo on Windows, macOS and Linux: `Demo on Windows, macOS and Linux` workflow runs `scripts/demo.py` and `scripts/demo_smoke.py` on each, plus an iPhone check in Safari's engine on macOS.
- Not tested: a real Zerodha account, a real Telegram bot, a real CAS statement, and a physical phone.
- The backtesting engine (`ml/backtest/engine.py`) simulates a single ticker's history; it hasn't been run across the full NIFTY-50 universe.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 👤 Author

Built as part of B.Tech Computer Science curriculum — designed to production standards for real-world deployment.

> *"The goal was not to build a student project. The goal was to build something that could run in production."*

## Trader and investor tools

`backend/tools/` holds pure-Python calculators (no database), exposed under `/api/v1/tools/*` and used by the **Tools** page in `frontend-react`. Run `pytest backend/tests` to test them.

| Trader | Investor |
| --- | --- |
| position size and stop, trade costs, trade journal, option price/Greeks, payoff builder, OI and max pain, daily loss limit, pre-trade checklist, expiry dates, screener, backtester | portfolio allocation, portfolio risk, XIRR, SIP and goal planner, rebalancing, quality score, announcement digest, capital gains estimate |

Also in the library but not yet wired to the UI: alert rules with Telegram/WhatsApp senders (`alerts.py`, needs your bot tokens) and a factor ranker (`factors.py`, only worth using if it passes its own out-of-sample test on real data).

Be aware of the limits:
- The screener, backtester, portfolio risk and forecast pages use **placeholder prices** until you load real data (below). Every response and screen says which one you are looking at, and outside development the API refuses to serve placeholders.
- Exchange charges and brokerage are approximate. Margin for sold options is not estimated (use your broker's SPAN calculator).
- The capital gains view is an estimate for listed-equity delivery trades. Have a chartered accountant confirm before filing.
- Nothing here predicts prices. Where the forecast model has no proven edge, the app shows a likely range only.

## Real market data

```bash
python scripts/check_nse_format.py          # confirms NSE's current files match what the code expects (paste the output if it says FAIL)
python scripts/fetch_data.py --years 3      # downloads NSE daily and index files into ./data (2 s between requests, cached, safe to re-run)
# in .env:  DATA_PROVIDER=nse
python scripts/capture_screens.py           # screenshots of every page; anything on placeholder or fixture data is renamed PLACEHOLDER-...
```

Then restart the API. `fetch_data.py` ends with a spot check of RELIANCE, TCS, HDFCBANK and INFY: compare their last close with a chart you trust.

- **Source:** NSE's daily cash-market file and index file. Layouts are matched by name against the current format and two older ones. The current layout was checked against NSE's published file list and independent write-ups, not a live download from the build environment, so `check_nse_format.py` on your machine is the real test.
- **Adjustment:** splits and bonuses are adjusted using the exchange's own previous close. Put a `data/dividends.csv` next to the store (columns `symbol, ex_date, amount`, or an NSE corporate-actions export with a Purpose column like "Interim Dividend - Rs 5 Per Share") and prices become total-return; without it dividends are not added back, and every screen says which you have.
- **Index:** Nifty 50 and India VIX come from NSE's index file. They feed portfolio-risk betas and the forecast model's market features. Without them, betas fall back to the average of the most liquid stocks and the page says so.
- **Date check:** each file's date is checked against the date requested, because NSE can serve the previous session's file. Raw files are kept unchanged in `data/raw`.
- **Licence:** NSE's files are NSE's data. Read [LICENSING.md](LICENSING.md). Production refuses to serve NSE files unless `NSE_DATA_LICENSED=true`, and licensed vendor data goes in with `scripts/import_vendor_csv.py` and `DATA_PROVIDER=local`.
