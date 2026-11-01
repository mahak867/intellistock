"use client";

import * as React from "react";
import { useAuth } from "@/lib/auth-context";
import { getOhlcv, getPrediction } from "@/lib/api";
import { demoFan, demoOhlcv, rsi as calcRsi, sma, type Candle, type FanPoint } from "@/lib/demo";

export type MlMetrics = {
  model: string; horizon_days: number; walk_forward_samples: number; directional_accuracy: number;
  mae_log_return: number; mae_naive_baseline: number; beats_naive: boolean; band_coverage_80: number;
};
export type Series = { candles: Candle[]; fan: FanPoint[]; live: boolean; metrics?: MlMetrics };
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api/v1");

export function useSeries(ticker: string, horizon: number): Series | null {
  const { token } = useAuth();
  const [s, setS] = React.useState<Series | null>(null);
  React.useEffect(() => {
    let off = false;
    (async () => {
      if (token && token !== "demo") {
        try {
          const [o, p] = await Promise.all([getOhlcv(token, ticker, 260), getPrediction(token, ticker, horizon)]);
          const candles = o.data.map((r) => ({
            time: String(r.date ?? r.time ?? r.Date).slice(0, 10),
            open: Number(r.open), high: Number(r.high), low: Number(r.low), close: Number(r.close), volume: Number(r.volume ?? 0),
          }));
          const fan = p.predictions.map((x) => ({ time: x.date.slice(0, 10), mean: x.predicted_close, lo: x.lower_bound, hi: x.upper_bound }));
          if (!off && candles.length > 60) return setS({ candles, fan, live: true });
        } catch { /* fall through to demo data */ }
      }
      try {
        const r = await fetch(`${API_ORIGIN}/demo/forecast/${encodeURIComponent(ticker)}?horizon=${horizon}`);
        if (r.ok) {
          const d = await r.json();
          if (!off) return setS({ candles: d.candles, fan: d.fan, live: false, metrics: d.metrics });
          return;
        }
      } catch { /* API offline: fall back to the in-browser placeholder */ }
      if (!off) {
        const candles = demoOhlcv(ticker);
        setS({ candles, fan: demoFan(candles, horizon), live: false });
      }
    })();
    return () => { off = true; };
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

