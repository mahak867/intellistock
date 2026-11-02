"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { useSeries, readSignal, dataLabel } from "@/lib/series";
import { PriceChart } from "@/components/terminal/price-chart";
import { cn } from "@/lib/utils";

const HORIZONS = [1, 3, 5, 7, 14, 30];
const inr = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function PredictionsInner() {
  const params = useSearchParams();
  const [input, setInput] = React.useState((params.get("ticker") || "RELIANCE").toUpperCase());
  const [ticker, setTicker] = React.useState(input);
  const [horizon, setHorizon] = React.useState(7);
  const series = useSeries(ticker, horizon);
  const last = series?.candles.at(-1)?.close ?? 0;
  const sig = series ? readSignal(series.candles, series.fan) : null;

  return (
    <div className="min-w-0 space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold tracking-tight">Forecast</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Day-by-day price range for {ticker}
            {series && `, ${dataLabel(series)}`}
          </p>
        </div>
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => { e.preventDefault(); if (input.trim()) setTicker(input.trim().toUpperCase()); }}
        >
          <label htmlFor="t" className="sr-only">NSE ticker</label>
          <input
            id="t" value={input} onChange={(e) => setInput(e.target.value)} placeholder="NSE ticker"
            className="font-num h-9 w-40 rounded-lg border border-border bg-card px-3 text-sm uppercase outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30"
          />
          <button type="submit"
            className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-transform duration-150 active:scale-[0.97] focus-visible:outline-2 outline-offset-2 outline-primary">
            Show forecast
          </button>
          <div role="group" aria-label="Forecast days" className="flex rounded-lg border border-border bg-card p-0.5 text-xs">
            {HORIZONS.map((h) => (
              <button key={h} onClick={() => setHorizon(h)} aria-pressed={h === horizon}
                className={cn("rounded-md px-2.5 py-1.5 font-medium transition-colors duration-150 focus-visible:outline-2 outline-primary",
                  h === horizon ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground")}>
                {h}d
              </button>
            ))}
          </div>
        </form>
      </header>

      <div className="h-[420px] min-w-0 overflow-hidden rounded-xl border border-border bg-card p-1">
        {series && <PriceChart candles={series.candles} fan={series.fan} showMA showFan />}
      </div>

      {series && sig && (
        <section className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
          <div>
            <h2 className="font-display text-lg font-semibold mb-3">Expected range</h2>
            <div className="overflow-x-auto rounded-xl border border-border bg-card">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 font-normal">Date</th>
                    <th className="px-3 py-2.5 text-right font-normal">Low</th>
                    <th className="px-3 py-2.5 text-right font-normal">Expected</th>
                    <th className="px-3 py-2.5 text-right font-normal">High</th>
                    <th className="px-4 py-2.5 text-right font-normal">vs today</th>
                  </tr>
                </thead>
                <tbody>
                  {series.fan.map((f) => {
                    const d = (f.mean / last - 1) * 100;
                    return (
                      <tr key={f.time} className="border-b border-border/60 last:border-0">
                        <td className="font-num px-4 py-2 text-muted-foreground">{f.time}</td>
                        <td className="font-num px-3 text-right">{inr(f.lo)}</td>
                        <td className="font-num px-3 text-right font-medium">{inr(f.mean)}</td>
                        <td className="font-num px-3 text-right">{inr(f.hi)}</td>
                        <td className={cn("font-num px-4 text-right", d >= 0 ? "text-success" : "text-destructive")}>{d >= 0 ? "+" : ""}{d.toFixed(2)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <h2 className="font-display text-lg font-semibold mb-3">Model read</h2>
            <div className="space-y-4 rounded-xl border border-border bg-card p-5">
              {series.metrics?.has_edge ? (
                <>
                  <p className="font-display text-3xl font-bold">{sig.label}</p>
                  <ul className="space-y-1.5 text-[13px] text-muted-foreground">
                    {sig.why.map((w) => <li key={w}>{w}</li>)}
                  </ul>
                </>
              ) : (
                <>
                  <p className="font-display text-2xl font-bold leading-tight">Range only</p>
                  <p role="status" className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
                    {series.metrics
                      ? "No Buy or Sell call. In testing, this model could not predict direction better than assuming the price stays put. The range below is the useful part."
                      : "Direction is not verified for this stock yet."}
                  </p>
                </>
              )}
              {series.metrics && <ModelQuality m={series.metrics} />}
              <p className="border-t border-border pt-3 text-xs text-muted-foreground">
                {series.live
                  ? "The band is the model's own interval from the API."
                  : (series.source === "nse" || series.source === "local")
                    ? `Trained and tested on NSE end-of-day prices (as of ${series.asOf}), split-adjusted, dividends not added back. The test numbers above are out-of-sample.`
                    : "Placeholder prices: this shows how the model is tested, not how it performs on real stocks."}
                {series.issues && series.issues.length > 0 && <span className="mt-1 block text-warning">Data notes: {series.issues.slice(0, 3).join("; ")}</span>}
              </p>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

function ModelQuality({ m }: { m: NonNullable<ReturnType<typeof useSeries>>["metrics"] & object }) {
  const rows: [string, string, string?][] = [
    ["Direction right", `${(m.directional_accuracy * 100).toFixed(0)}%`, "50% is a coin flip"],
    ["Direction beats \"no change\"", m.has_edge ? "Yes" : "No", `error ${(m.mae_log_return * 100).toFixed(2)}% vs ${(m.mae_naive_baseline * 100).toFixed(2)}%`],
    ["Volatility beats naive", m.vol_beats_naive ? "Yes" : "No", `error ${m.vol_mae_log.toFixed(3)} vs ${m.vol_naive_mae_log.toFixed(3)} (log)`],
    ["Range holds actual", `${(m.band_coverage_80 * 100).toFixed(0)}%`, "target 80%"],
    ["Tested on", `${m.walk_forward_samples} days`, m.market_features ? "walk-forward, with index and VIX" : "walk-forward, price history only"],
  ];
  return (
    <dl className="space-y-2.5 border-t border-border pt-3 text-sm">
      <dt className="text-xs text-muted-foreground">{m.model}</dt>
      {rows.map(([k, v, note]) => (
        <div key={k} className="flex items-baseline justify-between gap-3">
          <dd className="text-muted-foreground">{k}{note && <span className="block text-[11px] opacity-70">{note}</span>}</dd>
          <dd className={cn("font-num", (k.startsWith("Direction beats") || k.startsWith("Volatility")) && (v === "Yes" ? "text-success" : "text-destructive"))}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function PredictionsPage() {
  return (
    <React.Suspense fallback={null}>
      <PredictionsInner />
    </React.Suspense>
  );
}
