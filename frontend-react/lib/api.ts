const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** The API sends `detail` as a string, or as a list of {loc, msg} for validation errors. Always return readable text. */
export function formatDetail(detail: unknown, fallback = "Request failed"): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => {
        const field = Array.isArray(d?.loc) ? d.loc.filter((x: unknown) => x !== "body").join(" ") : "";
        const msg = String(d?.msg ?? "invalid").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
  }
  return fallback;
}

async function request<T>(
  path: string,
  token: string | null,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, formatDetail(body.detail));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ── Auth ─────────────────────────────────────────────────────────────────
export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new ApiError(res.status, formatDetail(body.detail, "Login failed"));
  }
  return res.json();
}

export async function register(email: string, password: string, fullName: string) {
  return request<{ message: string }>("/auth/register", null, {
    method: "POST",
    body: JSON.stringify({ email, password, full_name: fullName }),
  });
}

export async function getMe(token: string) {
  return request<{ id: string; email: string; full_name: string; role: string }>(
    "/auth/me",
    token
  );
}

// ── Predictions ──────────────────────────────────────────────────────────
export interface PredictionPoint {
  date: string;
  predicted_close: number;
  lower_bound: number;
  upper_bound: number;
}

export interface SignalResponse {
  ticker: string;
  signal: "BUY" | "SELL" | "HOLD";
  confidence: number;
  current_price: number;
  predicted_price: number;
  predicted_return_pct: number;
  rsi: number;
  macd_bullish: boolean;
  generated_at: string;
  model_version: string;
}

export interface PredictionResponse {
  ticker: string;
  predictions: PredictionPoint[];
  signal: SignalResponse;
  metrics: {
    RMSE: number;
    MAE: number;
    MAPE: number;
    Directional_Accuracy: number;
    model_version?: string;
    n_samples?: number;
  };
  model_version: string;
  cached: boolean;
  generated_at: string;
}

export async function getPrediction(
  token: string,
  ticker: string,
  horizonDays = 5
): Promise<PredictionResponse> {
  return request(`/predictions/${ticker}?horizon_days=${horizonDays}`, token);
}

export async function getSignal(token: string, ticker: string): Promise<SignalResponse> {
  return request(`/predictions/${ticker}/signal`, token);
}

export async function getPredictionHistory(token: string, ticker: string, days = 90) {
  return request<{ history: Record<string, unknown>[] }>(
    `/predictions/${ticker}/history?days=${days}`,
    token
  );
}

export interface BacktestTrade {
  entry_date: string;
  entry_price: number;
  exit_date: string | null;
  exit_price: number | null;
  pnl_pct: number | null;
}

export interface BacktestMetrics {
  total_return_pct: number;
  cagr_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number | null;
  calmar_ratio: number | null;
  win_rate_pct: number;
  num_trades: number;
  profit_factor: number | null;
}

export interface BacktestResponse {
  ticker: string;
  backtest_days: number;
  initial_capital: number;
  transaction_cost_pct: number;
  allow_short: boolean;
  dates: string[];
  strategy_equity: number[];
  benchmark_equity: number[];
  signals: string[];
  trades: BacktestTrade[];
  strategy_metrics: BacktestMetrics;
  benchmark_metrics: BacktestMetrics;
}

export async function runBacktest(
  token: string,
  ticker: string,
  days = 90,
  allowShort = true
): Promise<BacktestResponse> {
  return request(
    `/predictions/${ticker}/backtest?days=${days}&allow_short=${allowShort}`,
    token
  );
}

// ── Stocks / Watchlist ───────────────────────────────────────────────────
export async function getWatchlist(token: string) {
  return request<{
    watchlist: { id: string; ticker: string; exchange: string; notes: string | null }[];
    count: number;
  }>("/stocks/watchlist", token);
}

export async function addToWatchlist(token: string, ticker: string) {
  return request("/stocks/watchlist", token, {
    method: "POST",
    body: JSON.stringify({ ticker, exchange: "NSE" }),
  });
}

export async function removeFromWatchlist(token: string, itemId: string) {
  return request(`/stocks/watchlist/${itemId}`, token, { method: "DELETE" });
}

export interface OHLCVResponse {
  ticker: string;
  exchange: string;
  currency: string;
  days: number;
  data: Record<string, number | string>[];
  cached: boolean;
}

export async function getOhlcv(token: string, ticker: string, days = 180): Promise<OHLCVResponse> {
  return request(`/stocks/${ticker}/ohlcv?days=${days}`, token);
}

// ── Users: portfolio / alerts / profile ──────────────────────────────────
export async function getPortfolio(token: string) {
  return request<{
    portfolio: {
      id: string;
      ticker: string;
      quantity: number;
      avg_buy_price: number;
      invested_value: number;
      buy_date: string;
    }[];
    count: number;
  }>("/users/portfolio", token);
}

export async function addPortfolioEntry(
  token: string,
  entry: { ticker: string; quantity: number; avg_buy_price: number; buy_date: string; exchange?: string }
) {
  return request<{ message: string; id: string }>("/users/portfolio", token, {
    method: "POST",
    body: JSON.stringify({ exchange: "NSE", ...entry }),
  });
}

export async function removePortfolioEntry(token: string, entryId: string) {
  return request(`/users/portfolio/${entryId}`, token, { method: "DELETE" });
}

export async function updateProfile(token: string, fullName: string) {
  return request<{ message: string; full_name: string }>("/users/me", token, {
    method: "PATCH",
    body: JSON.stringify({ full_name: fullName }),
  });
}

export async function getAlerts(token: string) {
  return request<{
    alerts: {
      id: string;
      ticker: string;
      alert_type: string;
      is_active: boolean;
      trigger_count: number;
    }[];
    count: number;
  }>("/users/alerts", token);
}
