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

export type AlertType = "price_above" | "price_below" | "vol_spike";

export interface AlertRow {
  id: string;
  ticker: string;
  alert_type: string;
  price_target: number | null;
  is_active: boolean;
  trigger_count: number;
  last_triggered: string | null;
  last_message: string | null;
}

export interface AlertCheck {
  checked: number;
  fired: { id: string; ticker: string; message: string; delivered: boolean | null }[];
  skipped: { ticker: string; reason: string | null }[];
  data_source: string;
  real_data: boolean;
}

export interface AlertSettings {
  telegram_chat_id: string | null;
  telegram_available: boolean;
  real_data: boolean;
  check_every_minutes: number;
  note: string;
}

export async function getAlerts(token: string) {
  return request<{ alerts: AlertRow[]; count: number }>("/users/alerts", token);
}

export async function addAlert(token: string, a: { ticker: string; alert_type: AlertType; price_target: number }) {
  return request<{ message: string; id: string }>("/users/alerts", token, { method: "POST", body: JSON.stringify(a) });
}

export async function removeAlert(token: string, id: string) {
  return request(`/users/alerts/${id}`, token, { method: "DELETE" });
}

export async function rearmAlert(token: string, id: string) {
  return request(`/users/alerts/${id}/rearm`, token, { method: "POST" });
}

export async function checkAlerts(token: string) {
  return request<AlertCheck>("/users/alerts/check", token, { method: "POST" });
}

export async function getAlertSettings(token: string) {
  return request<AlertSettings>("/users/alerts/settings", token);
}

export async function saveTelegramChat(token: string, chatId: string) {
  return request("/users/me", token, { method: "PATCH", body: JSON.stringify({ telegram_chat_id: chatId }) });
}

export async function testTelegram(token: string) {
  return request<{ message: string }>("/users/alerts/test-telegram", token, { method: "POST" });
}

export async function sendFeedback(token: string, f: { category: "bug" | "data" | "feature" | "other"; message: string; page?: string }) {
  return request<{ message: string; id: string }>("/users/feedback", token, { method: "POST", body: JSON.stringify(f) });
}

export async function getMarketStatus(token: string | null) {
  return request<{ provider: string; real_data: boolean; licensed_to_serve: boolean; note: string; last?: string; symbols?: number }>("/market/status", token);
}

// ── Broker (Zerodha Kite Connect) ────────────────────────────────────────
export interface BrokerStatus {
  connected: boolean;
  broker: string | null;
  session_valid: boolean;
  orders_enabled: boolean;
  api_key?: string;
  broker_user_id?: string | null;
  broker_user_name?: string | null;
  session_expires_at?: string | null;
  login_url?: string;
}
export interface BrokerHolding { ticker: string; exchange: string; quantity: number; avg_buy_price: number; last_price: number | null; pnl: number | null }
export interface OrderTicket { tradingsymbol: string; exchange: "NSE" | "BSE"; side: "BUY" | "SELL"; quantity: number; price: number; product: "CNC" | "MIS" }
export interface OrderPreview {
  order: OrderTicket; order_type: string; validity: string; value: number; last_price: number | null; gap_from_last_pct: number | null;
  charges_estimate: number; warnings: string[]; confirm_token: string; expires_in_seconds: number;
}
export interface OrderLogRow { id: string; time: string | null; symbol: string; exchange: string; side: string; quantity: number; price: number; product: string; status: string; broker_order_id: string | null; message: string | null }

export const getBrokerStatus = (token: string) => request<BrokerStatus>("/broker/status", token);
export const saveBrokerKeys = (token: string, api_key: string, api_secret: string) =>
  request<BrokerStatus & { message: string }>("/broker/kite/keys", token, { method: "PUT", body: JSON.stringify({ api_key, api_secret }) });
export const finishBrokerLogin = (token: string, request_token: string) =>
  request<BrokerStatus & { message: string }>("/broker/kite/session", token, { method: "POST", body: JSON.stringify({ request_token }) });
export const disconnectBroker = (token: string) => request("/broker", token, { method: "DELETE" });
export const getBrokerHoldings = (token: string) => request<{ holdings: BrokerHolding[]; as_of: string }>("/broker/holdings", token);
export const importBrokerHoldings = (token: string, mode: "merge" | "replace") =>
  request<{ added: number; updated: number; removed: number; note: string | null }>("/broker/holdings/import", token, { method: "POST", body: JSON.stringify({ mode }) });
export const getLiveQuotes = (token: string, tickers: string[]) =>
  request<{ prices: Record<string, number>; missing: string[]; as_of: string }>(`/broker/quotes?tickers=${encodeURIComponent(tickers.join(","))}`, token);
export const previewOrder = (token: string, o: OrderTicket) =>
  request<OrderPreview>("/broker/orders/preview", token, { method: "POST", body: JSON.stringify(o) });
export const placeOrder = (token: string, o: OrderTicket, confirm_token: string) =>
  request<{ message: string; broker_order_id: string; status: string }>("/broker/orders", token, { method: "POST", body: JSON.stringify({ ...o, confirm_token }) });
export const getOrderLog = (token: string) => request<{ orders: OrderLogRow[] }>("/broker/orders", token);
