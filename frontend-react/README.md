# IntelliStock — React Dashboard (ReUI)

A full React/Next.js dashboard for the IntelliStock backend, built with real
[ReUI](https://github.com/keenthemes/reui) components (MIT-licensed, cloned
from source — not the hosted `shadcn add` registry, which isn't reachable
from every network) retheme'd into a dark navy/saffron palette.

This is an **alternative to the Streamlit dashboard** in `../frontend/`, not
a replacement — both talk to the same FastAPI backend and can run side by
side. Pick whichever fits your workflow; nothing in the backend cares which
one you use.

## Pages

- **Login** — JWT auth against the backend
- **Dashboard** — watchlist with live signal cards
- **Predictions** — ticker/horizon controls, BUY/SELL/HOLD signal panel,
  price+forecast / volume / RSI charts (Recharts)
- **Portfolio** — holdings with live-calculated unrealized P&L
- **Backtesting** — walk-forward long/short simulation vs. buy-and-hold,
  with Sharpe/Sortino/max-drawdown/Calmar/win-rate/profit-factor
- **Settings** — profile

## Setup

```bash
npm install
echo "NEXT_PUBLIC_API_BASE=http://localhost:8000/api/v1" > .env.local
npm run dev
```

Requires the backend (`../backend/`) running and reachable at the URL in
`NEXT_PUBLIC_API_BASE`.

## Stack

Next.js 16 (App Router), TypeScript, Tailwind CSS v4, Radix UI primitives
(via the unified `radix-ui` package), Recharts, `lucide-react`.

## Where the ReUI code lives

`registry/` and `registry-reui/` are the actual ReUI component source
(Button, Card, Badge, Select, Tabs, Chart, etc.), copied in with their
original import paths intact. `app/globals.css` retheme's ReUI's own CSS
token system (`--primary`, `--chart-1..5`, etc.) rather than forking the
components themselves — upstream ReUI updates should drop in cleanly.

## Build

```bash
npm run build && npm start
```
