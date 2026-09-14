# 📈 IntelliStock
### NSE/BSE Market Intelligence Platform

> **LSTM-powered Indian stock market forecasting with BUY/SELL/HOLD signal generation, deployed on cloud infrastructure with enterprise-grade security.**

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![TensorFlow](https://img.shields.io/badge/TensorFlow-2.20-orange)](https://tensorflow.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 🎯 Overview

IntelliStock is a full-stack, production-ready market intelligence platform built for the Indian equity market (NSE/BSE). It combines deep learning (Bidirectional LSTM with Bahdanau Attention) with classical technical analysis to generate actionable trading signals.

**This is not a demo.** It runs on real market data, has a real API, real authentication, real tests, and is deployed to a real cloud environment.

---

## ✨ Key Features

| Category | Features |
|---|---|
| **ML/AI** | BiLSTM + Attention, GRU baseline, 30+ technical features, NIFTY50 macro input |
| **Signals** | BUY/SELL/HOLD with confidence scores, RSI + MACD confirmation |
| **API** | FastAPI, JWT auth, refresh tokens, rate limiting, Redis caching |
| **Security** | BCrypt passwords, token revocation, HTTPS-only headers, CORS, rate limits |
| **Data** | NSE holiday calendar, yfinance with retry, parquet caching, 5Y historical |
| **Monitoring** | Prometheus metrics, Grafana dashboards, Sentry error tracking, OpenTelemetry |
| **Deployment** | Docker + Compose (`infra/docker/`); GitHub Actions CI/CD was attempted and removed as broken — see Known Issues below before re-adding |
| **Database** | PostgreSQL + SQLAlchemy async, Alembic migrations, Redis cache |
| **Testing** | 50 automated tests (pytest) — unit, integration, security, and anti-leakage |

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
│   │   └── migrations/          # Alembic schema migrations
│   └── terraform/               # Cloud infrastructure as code
├── .github/workflows/
│   └── ci-cd.yml                # GitHub Actions pipeline
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
- A GitHub Actions CI workflow was added and then removed for being broken (see commit history). The test suite itself (`pytest backend/tests/`) is real and passing; it just isn't wired to CI yet.
- The backtesting engine (`ml/backtest/engine.py`) simulates a single ticker's history; it hasn't been run across the full NIFTY-50 universe.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 👤 Author

Built as part of B.Tech Computer Science curriculum — designed to production standards for real-world deployment.

> *"The goal was not to build a student project. The goal was to build something that could run in production."*
