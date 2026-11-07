// Deterministic synthetic market data so the UI works without the API or
// Yahoo Finance. Anything built from this is labelled "Demo data" on screen.
export type Candle = { time: string; open: number; high: number; low: number; close: number; volume: number };
export type FanPoint = { time: string; mean: number; lo: number; hi: number };

export const SECTORS: Record<string, string[]> = {
  IT: ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
  Banks: ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"],
  Energy: ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA"],
  Auto: ["MARUTI", "TMPV", "M&M", "BAJAJ-AUTO"],
  FMCG: ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA"],
  Metals: ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
};
export const ALL_TICKERS = Object.values(SECTORS).flat();

function hash(s: string) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}
function rng(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const gauss = (r: () => number) => Math.sqrt(-2 * Math.log(r() || 1e-9)) * Math.cos(2 * Math.PI * r());

function bizDays(end: Date, n: number) {
  const out: string[] = [];
  const d = new Date(end);
  while (out.length < n) {
    if (d.getUTCDay() % 6 !== 0) out.unshift(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out;
}

export function demoOhlcv(ticker: string, days = 260): Candle[] {
  const r = rng(hash(ticker));
  const base = 200 + (hash(ticker) % 3000);
  const vol = 0.011 + r() * 0.011;
  const drift = 0.0004 + gauss(r) * 0.0002;
  const phase = 3 + r() * 4;
  let close = base;
  return bizDays(new Date(), days).map((time, i) => {
    const ret = drift + gauss(r) * vol + Math.sin((i / days) * phase) * 0.0009;
    const open = close * (1 + gauss(r) * 0.002);
    close = close * Math.exp(ret);
    const span = Math.abs(gauss(r)) * vol * 0.7 * close;
    return {
      time, open, close,
      high: Math.max(open, close) + span,
      low: Math.min(open, close) - span,
      volume: Math.round(Math.exp(14.2 + gauss(r) * 0.35) * (1 + 6 * Math.abs(ret))),
    };
  });
}

export function sma(c: Candle[], n: number) {
  return c.flatMap((_, i) =>
    i < n - 1 ? [] : [{ time: c[i].time, value: c.slice(i - n + 1, i + 1).reduce((a, x) => a + x.close, 0) / n }]
  );
}
export function rsi(c: Candle[], n = 14) {
  let g = 0, l = 0;
  for (let i = c.length - 120; i < c.length; i++) {
    if (i < 1) continue;
    const d = c[i].close - c[i - 1].close;
    g = (g * (n - 1) + Math.max(d, 0)) / n;
    l = (l * (n - 1) + Math.max(-d, 0)) / n;
  }
  return l === 0 ? 100 : 100 - 100 / (1 + g / l);
}

export function demoFan(c: Candle[], horizon: number): FanPoint[] {
  const rets = c.slice(-60).map((x, i, a) => (i ? x.close / a[i - 1].close - 1 : 0)).slice(1);
  const mu = rets.reduce((a, b) => a + b, 0) / rets.length;
  const sd = Math.sqrt(rets.reduce((a, b) => a + (b - mu) ** 2, 0) / rets.length);
  const last = c[c.length - 1];
  const start = new Date(last.time + "T00:00:00Z");
  start.setUTCDate(start.getUTCDate() + 1);
  const days = bizDays(new Date(start.getTime() + horizon * 1.6 * 864e5), 400).filter((d) => d >= start.toISOString().slice(0, 10)).slice(0, horizon);
  return days.map((time, i) => {
    const k = i + 1;
    const mean = last.close * Math.exp(mu * k * 0.6);
    const band = last.close * sd * Math.sqrt(k) * 1.28;
    return { time, mean, lo: mean - band, hi: mean + band };
  });
}

export function demoQuote(ticker: string) {
  const c = demoOhlcv(ticker);
  const last = c[c.length - 1], prev = c[c.length - 2];
  return { ticker, price: last.close, chg: (last.close / prev.close - 1) * 100, spark: c.slice(-30).map((x) => x.close), rsi: rsi(c) };
}
