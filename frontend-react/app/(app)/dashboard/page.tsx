"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { getOhlcv, getPrediction } from "@/lib/api";
import {
  ALL_TICKERS, SECTORS, demoFan, demoOhlcv, demoQuote, rsi as calcRsi, sma,
  type Candle, type FanPoint,
} from "@/lib/demo";
import { PriceChart, type Hover } from "@/components/terminal/price-chart";
import { Sparkline } from "@/components/terminal/sparkline";
import { cn } from "@/lib/utils";

const inr = (n: number, d = 2) => n.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const HORIZONS = [5, 10, 15, 30];

type Series = { candles: Candle[]; fan: FanPoint[]; live: boolean };

function useSeries(ticker: string, horizon: number): Series | null {
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
      if (!off) {
        const candles = demoOhlcv(ticker);
        setS({ candles, fan: demoFan(candles, horizon), live: false });
      }
    })();
    return () => { off = true; };
  }, [ticker, horizon, token]);
  return s;
}

function readSignal(candles: Candle[], fan: FanPoint[]) {
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

export default function DashboardPage() {
  const [ticker, setTicker] = React.useState("RELIANCE");
  const [horizon, setHorizon] = React.useState(10);
  const [showMA, setShowMA] = React.useState(true);
  const [showFan, setShowFan] = React.useState(true);
  const [hover, setHover] = React.useState<Hover>(null);
  const series = useSeries(ticker, horizon);

  const last = series?.candles.at(-1);
  const prev = series?.candles.at(-2);
  const shown = hover ?? last;
  const chg = last && prev ? (last.close / prev.close - 1) * 100 : 0;
  const sig = series ? readSignal(series.candles, series.fan) : null;
  const pos = sig ? 50 + (Math.max(-3, Math.min(3, sig.score)) / 3) * 42 : 50;

  return (
    <div className="min-w-0 space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-1">
          <div>
            <label htmlFor="sym" className="sr-only">Symbol</label>
            <select
              id="sym" value={ticker} onChange={(e) => setTicker(e.target.value)}
              className="font-display text-4xl font-bold tracking-tight bg-transparent -ml-1 cursor-pointer rounded px-1 focus-visible:outline-2 outline-primary appearance-none"
            >
              {ALL_TICKERS.map((t) => <option key={t} value={t} className="bg-card text-base font-sans">{t}</option>)}
            </select>
            <p className="text-xs text-muted-foreground mt-0.5">NSE · daily · {series?.live ? "model forecast" : "Demo data, synthetic"}</p>
          </div>
          {last && (
            <div className="font-num pb-1">
              <span className="text-2xl">₹{inr(last.close)}</span>
              <span className={cn("ml-3 text-sm", chg >= 0 ? "text-success" : "text-destructive")}>{chg >= 0 ? "+" : ""}{chg.toFixed(2)}%</span>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Seg label="Forecast days">
            {HORIZONS.map((h) => <Chip key={h} on={h === horizon} onClick={() => setHorizon(h)}>{h}d</Chip>)}
          </Seg>
          <Seg label="Overlays">
            <Chip on={showMA} onClick={() => setShowMA(!showMA)}>Averages</Chip>
            <Chip on={showFan} onClick={() => setShowFan(!showFan)}>Forecast</Chip>
          </Seg>
        </div>
      </header>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 overflow-hidden rounded-xl border border-border bg-card">
          <div className="font-num flex h-9 overflow-hidden whitespace-nowrap items-center gap-5 border-b border-border px-4 text-xs text-muted-foreground" aria-live="off">
            {shown ? (
              <>
                <span>{shown.time}</span>
                <span>O <b className="font-medium text-foreground">{inr(shown.open)}</b></span>
                <span>H <b className="font-medium text-foreground">{inr(shown.high)}</b></span>
                <span>L <b className="font-medium text-foreground">{inr(shown.low)}</b></span>
                <span>C <b className="font-medium text-foreground">{inr(shown.close)}</b></span>
              </>
            ) : <span>Loading…</span>}
            <span className="ml-auto hidden sm:flex items-center gap-3">
              <i className="inline-block h-[3px] w-4 rounded bg-primary" /> forecast
              <i className="inline-block h-px w-4 bg-[#e6b450]" /> 20d
              <i className="inline-block h-px w-4 bg-[#7dd3fc]" /> 50d
            </span>
          </div>
          <div className="h-[460px] p-1">
            {series && <PriceChart candles={series.candles} fan={series.fan} showMA={showMA} showFan={showFan} onHover={setHover} />}
          </div>
        </div>

        <aside className="rounded-xl border border-border bg-card p-5 space-y-5">
          <div>
            <p className="text-xs text-muted-foreground">Model read</p>
            <p className="font-display text-4xl font-bold mt-1">{sig?.label ?? "…"}</p>
            <div className="relative mt-4 h-1.5 rounded-full" style={{ background: "linear-gradient(90deg,#ee7167,#2a2a3a 50%,#45bfa6)" }}>
              <span
                className="absolute top-1/2 h-4 w-1.5 -translate-y-1/2 -translate-x-1/2 rounded-sm bg-foreground transition-[left] duration-300"
                style={{ left: `${pos}%`, transitionTimingFunction: "var(--ease-out)" }}
              />
            </div>
            <div className="mt-1.5 flex justify-between text-[11px] text-muted-foreground"><span>Sell</span><span>Hold</span><span>Buy</span></div>
          </div>
          {sig && (
            <>
              <dl className="font-num text-sm space-y-2.5">
                <Row k={`Expected, ${horizon}d`} v={`${sig.exp >= 0 ? "+" : ""}${(sig.exp * 100).toFixed(1)}%`} tone={sig.exp >= 0 ? "up" : "down"} />
                <Row k="RSI (14)" v={sig.rsi.toFixed(0)} />
                <Row k="52-week range" v={`${inr(Math.min(...series!.candles.slice(-250).map((c) => c.low)), 0)} – ${inr(Math.max(...series!.candles.slice(-250).map((c) => c.high)), 0)}`} />
              </dl>
              <ul className="space-y-1.5 border-t border-border pt-4 text-[13px] text-muted-foreground">
                {sig.why.map((w) => <li key={w}>{w}</li>)}
              </ul>
            </>
          )}
          <p className="text-[11px] leading-snug text-muted-foreground">Not investment advice. {series && !series.live && "Forecast here is a statistical placeholder."}</p>
        </aside>
      </section>

      <section className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Watchlist onPick={setTicker} active={ticker} />
        <Heat onPick={setTicker} />
      </section>
    </div>
  );
}

function Seg({ label, children }: { label: string; children: React.ReactNode }) {
  return <div role="group" aria-label={label} className="flex rounded-lg border border-border bg-card p-0.5">{children}</div>;
}
function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick} aria-pressed={on}
      className={cn(
        "rounded-md px-3 py-1.5 font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] focus-visible:outline-2 outline-primary",
        on ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground"
      )}
    >{children}</button>
  );
}
function Row({ k, v, tone }: { k: string; v: string; tone?: "up" | "down" }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="font-sans text-muted-foreground">{k}</dt>
      <dd className={cn(tone === "up" && "text-success", tone === "down" && "text-destructive")}>{v}</dd>
    </div>
  );
}

const WATCH = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "MARUTI"];
function Watchlist({ onPick, active }: { onPick: (t: string) => void; active: string }) {
  const rows = React.useMemo(() => WATCH.map(demoQuote), []);
  return (
    <div>
      <h2 className="font-display text-lg font-semibold mb-3">Watchlist</h2>
      <div className="overflow-x-auto rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground border-b border-border">
              <th className="px-4 py-2.5 font-normal">Symbol</th>
              <th className="px-3 py-2.5 font-normal text-right">Price</th>
              <th className="px-3 py-2.5 font-normal text-right">Day</th>
              <th className="px-3 py-2.5 font-normal hidden sm:table-cell">30 days</th>
              <th className="px-4 py-2.5 font-normal text-right">RSI</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.ticker} onClick={() => onPick(r.ticker)}
                className={cn("cursor-pointer border-b border-border/60 last:border-0 transition-colors hover:bg-accent", active === r.ticker && "bg-primary/[0.06]")}>
                <td className="px-4 py-2.5 font-medium">
                  <button className="focus-visible:outline-2 outline-primary rounded" onClick={() => onPick(r.ticker)}>{r.ticker}</button>
                </td>
                <td className="px-3 font-num text-right">₹{inr(r.price)}</td>
                <td className={cn("px-3 font-num text-right", r.chg >= 0 ? "text-success" : "text-destructive")}>{r.chg >= 0 ? "+" : ""}{r.chg.toFixed(2)}%</td>
                <td className="px-3 hidden sm:table-cell"><Sparkline data={r.spark} up={r.spark.at(-1)! >= r.spark[0]} /></td>
                <td className={cn("px-4 font-num text-right", r.rsi > 70 && "text-destructive", r.rsi < 30 && "text-success")}>{r.rsi.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">Quotes are demo data until the API serves live prices.</p>
    </div>
  );
}

function Heat({ onPick }: { onPick: (t: string) => void }) {
  const q = React.useMemo(() => Object.fromEntries(ALL_TICKERS.map((t) => [t, demoQuote(t).chg])), []);
  const tone = (c: number) => {
    const a = Math.min(Math.abs(c) / 3, 1) * 0.55 + 0.1;
    return c >= 0 ? `rgba(69,191,166,${a})` : `rgba(238,113,103,${a})`;
  };
  return (
    <div>
      <h2 className="font-display text-lg font-semibold mb-3">Sectors</h2>
      <div className="space-y-3">
        {Object.entries(SECTORS).map(([name, list]) => (
          <div key={name}>
            <p className="mb-1 text-xs text-muted-foreground">{name}</p>
            <div className="flex flex-wrap gap-1">
              {list.map((t) => (
                <button key={t} onClick={() => onPick(t)} style={{ background: tone(q[t]) }}
                  className="font-num rounded-md px-2.5 py-1.5 text-left text-[11px] leading-tight transition-transform duration-150 active:scale-[0.97] focus-visible:outline-2 outline-primary">
                  <span className="block font-medium">{t}</span>
                  <span className="opacity-80">{q[t] >= 0 ? "+" : ""}{q[t].toFixed(2)}%</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <Link href="/backtesting" className="mt-4 inline-block text-xs text-primary hover:underline">Backtest a strategy</Link>
    </div>
  );
}
