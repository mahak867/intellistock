"use client";

import * as React from "react";
import { useAuth } from "@/lib/auth-context";
import { getOhlcv, getPrediction } from "@/lib/api";
import { demoFan, demoOhlcv, rsi as calcRsi, sma, type Candle, type FanPoint } from "@/lib/demo";

export type MlMetrics = {
  model: string; horizon_days: number; walk_forward_samples: number; market_features: boolean;
  directional_accuracy: number; shrink: number; mae_log_return: number; mae_naive_baseline: number;
  beats_naive: boolean; has_edge: boolean; edge_t_stat: number;
  vol_mae_log: number; vol_naive_mae_log: number; vol_beats_naive: boolean;
  band_coverage_80: number; band_coverage_80_holdout: number; band_width_pct: number; daily_vol_pct: number;
};
export type Series = { candles: Candle[]; fan: FanPoint[]; live: boolean; metrics?: MlMetrics; source?: "synthetic" | "fixture" | "nse" | "local"; asOf?: string; issues?: string[] };

/** One honest sentence about where the prices on screen came from. */
export function dataLabel(s: Series | null): string {
  if (!s) return "";
  if (s.live) return "live data";
  if (s.source === "nse") return `NSE end-of-day prices, as of ${s.asOf}`;
  if (s.source === "local") return `local data store, as of ${s.asOf}`;
  if (s.source === "fixture") return "test fixture, synthetic prices in NSE layout";
  return "placeholder prices, not market data";
}
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api/v1");

const authHeaders = (token: string | null | undefined): Record<string, string> => (token && token !== "demo" ? { Authorization: `Bearer ${token}` } : {});

/** Price series for one stock. Order: the market API (real NSE data when configured), then the older
 *  provider-backed API, then an in-browser placeholder that is labelled as such. */
export function useSeries(ticker: string, horizon: number): Series | null {
  const { token } = useAuth();
  const [s, setS] = React.useState<Series | null>(null);
  React.useEffect(() => {
    let off = false;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 20000);
    (async () => {
      try {
        const r = await fetch(`${API_ORIGIN}/market/forecast/${encodeURIComponent(ticker)}?horizon=${horizon}`, { headers: authHeaders(token), signal: ctl.signal });
        if (r.ok) {
          const d = await r.json();
          if (!off) return setS({ candles: d.candles, fan: d.fan, live: false, metrics: d.metrics, source: d.source, asOf: d.as_of, issues: d.quality?.issues });
          return;
        }
      } catch { /* API offline or timed out: try the next source */ }
      if (off) return; // the page moved on: do not start more requests
      if (token && token !== "demo") {
        try {
          const [o, p] = await Promise.all([getOhlcv(token, ticker, 260), getPrediction(token, ticker, horizon)]);
          const candles = o.data.map((r) => ({
            time: String(r.date ?? r.time ?? r.Date).slice(0, 10),
            open: Number(r.open), high: Number(r.high), low: Number(r.low), close: Number(r.close), volume: Number(r.volume ?? 0),
          }));
          const fan = p.predictions.map((x) => ({ time: x.date.slice(0, 10), mean: x.predicted_close, lo: x.lower_bound, hi: x.upper_bound }));
          if (!off && candles.length > 60) return setS({ candles, fan, live: true });
        } catch { /* fall through to the placeholder */ }
      }
      if (!off) {
        const candles = demoOhlcv(ticker);
        setS({ candles, fan: demoFan(candles, horizon), live: false });
      }
    })();
    return () => { off = true; clearTimeout(timer); ctl.abort(); };
  }, [ticker, horizon, token]);
  return s;
}

export function readSignal(candles: Candle[], fan: FanPoint[]) {
  const last = candles[candles.length - 1];
  const s20 = sma(candles, 20).at(-1)!.value, s50 = sma(candles, 50).at(-1)!.value;
  const r = calcRsi(candles);
  const exp = fan.length ? fan[fan.length - 1].mean / last.close - 1 : 0;
  const why: string[] = [];
  let score = 0;
  if (exp > 0.01) { score++; why.push(`Forecast ${(exp * 100).toFixed(1)}% higher`); }
  else if (exp < -0.01) { score--; why.push(`Forecast ${(Math.abs(exp) * 100).toFixed(1)}% lower`); }
  else why.push("Forecast roughly flat");
  if (s20 > s50) { score++; why.push("20-day average above 50-day"); } else { score--; why.push("20-day average below 50-day"); }
  if (r < 30) { score++; why.push(`RSI ${r.toFixed(0)}, oversold`); }
  else if (r > 70) { score--; why.push(`RSI ${r.toFixed(0)}, overbought`); }
  else why.push(`RSI ${r.toFixed(0)}, neutral`);
  return { label: score >= 2 ? "Buy" : score <= -2 ? "Sell" : "Hold", score, why, exp, rsi: r };
}


export type Quote = { ticker: string; price: number; chg: number; spark: number[]; rsi: number };
/** Quotes from the dev demo API so every number on screen comes from the same synthetic market. */
export function useQuotes(tickers: string[]): Quote[] | null {
  const key = tickers.join(",");
  const { token } = useAuth();
  const [q, setQ] = React.useState<Quote[] | null>(null);
  React.useEffect(() => {
    let off = false;
    fetch(`${API_ORIGIN}/market/quotes?tickers=${encodeURIComponent(key)}`, { headers: authHeaders(token) })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!off) setQ(d); })
      .catch(() => { if (!off) setQ(null); });
    return () => { off = true; };
  }, [key, token]);
  return q;
}
