"use client";

import * as React from "react";
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from "recharts";
import { TrendingUp, TrendingDown, AlertTriangle } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { runBacktest, type BacktestResponse, type BacktestMetrics } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/registry/bases/radix/ui/chart";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const equityChartConfig = {
  strategy: { label: "IntelliStock strategy", color: "var(--chart-1)" },
  benchmark: { label: "Buy & hold", color: "var(--chart-3)" },
} satisfies ChartConfig;

const BADGE_VARIANT: Record<string, "success-light" | "destructive-light" | "warning-light"> = {
  BUY: "success-light",
  SELL: "destructive-light",
  HOLD: "warning-light",
};

function MetricRow({
  label,
  strategy,
  benchmark,
  suffix = "",
  higherIsBetter = true,
}: {
  label: string;
  strategy: number | null;
  benchmark: number | null;
  suffix?: string;
  higherIsBetter?: boolean;
}) {
  const fmt = (v: number | null) => (v === null ? "N/A" : `${v}${suffix}`);
  const strategyBetter =
    strategy !== null && benchmark !== null
      ? higherIsBetter
        ? strategy >= benchmark
        : strategy <= benchmark
      : null;
  return (
    <tr className="border-b border-border/60 last:border-0">
      <td className="py-2.5 pr-4 text-sm text-muted-foreground">{label}</td>
      <td
        className={`py-2.5 pr-4 text-right tabular text-sm font-medium ${
          strategyBetter === true ? "text-success" : strategyBetter === false ? "text-foreground" : ""
        }`}
      >
        {fmt(strategy)}
      </td>
      <td className="py-2.5 text-right tabular text-sm text-muted-foreground">{fmt(benchmark)}</td>
    </tr>
  );
}

export default function BacktestingPage() {
  const { token } = useAuth();
  const [ticker, setTicker] = React.useState("RELIANCE");
  const [days, setDays] = React.useState(90);
  const [allowShort, setAllowShort] = React.useState(true);
  const [result, setResult] = React.useState<BacktestResponse | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const run = async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await runBacktest(token, ticker, days, allowShort);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Backtest failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const chartData = React.useMemo(() => {
    if (!result) return [];
    return result.dates.map((date, i) => ({
      date,
      strategy: result.strategy_equity[i],
      benchmark: result.benchmark_equity[i],
    }));
  }, [result]);

  return (
    <div>
      <h1 className="font-display text-2xl font-semibold mb-1">Backtesting</h1>
      <p className="text-sm text-muted-foreground mb-4">
        Walk-forward simulation of the model&apos;s day-by-day signals vs. buy-and-hold —
        with transaction costs, not just a raw prediction log.
      </p>

      <Card className="mb-6 border-warning/30 bg-warning/5">
        <CardContent className="py-3 flex items-start gap-2.5">
          <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
          <p className="text-xs text-muted-foreground leading-relaxed">
            For research and educational purposes only. IntelliStock is not a SEBI-registered
            Investment Adviser or Research Analyst, and nothing here is a recommendation to buy
            or sell any security. Backtested performance does not reflect real trading and does
            not indicate future results.
          </p>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-end gap-3 mb-6">
        <div className="w-40">
          <Label htmlFor="bt-ticker" className="mb-1.5 block">Ticker</Label>
          <Input
            id="bt-ticker"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
          />
        </div>
        <div className="w-56">
          <Label htmlFor="bt-days" className="mb-1.5 block">
            Days to backtest: <span className="tabular text-foreground">{days}</span>
          </Label>
          <input
            id="bt-days"
            type="range"
            min={30}
            max={365}
            step={10}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="w-full accent-primary h-10"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground pb-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={allowShort}
            onChange={(e) => setAllowShort(e.target.checked)}
            className="accent-primary h-4 w-4"
          />
          Allow short selling
        </label>
        <Button onClick={run} disabled={loading}>
          {loading ? "Simulating…" : "Run backtest"}
        </Button>
      </div>

      {error && (
        <Card className="border-destructive/30 mb-4">
          <CardContent className="py-4 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      {result && (
        <>
          <Card className="mb-4">
            <CardHeader>
              <CardTitle className="text-foreground text-base">Equity curve</CardTitle>
              <CardDescription>
                ₹{result.initial_capital.toLocaleString("en-IN")} starting capital ·{" "}
                {(result.transaction_cost_pct * 100).toFixed(2)}% cost per trade ·{" "}
                {result.allow_short ? "long/short" : "long-only"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer config={equityChartConfig} className="h-[300px] w-full">
                <ComposedChart data={chartData} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis
                    dataKey="date"
                    tickLine={false}
                    axisLine={false}
                    tickMargin={8}
                    interval={Math.floor(chartData.length / 6)}
                  />
                  <YAxis tickLine={false} axisLine={false} width={64} domain={["auto", "auto"]} />
                  <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
                  <Line
                    type="monotone"
                    dataKey="strategy"
                    stroke="#f0a93b"
                    strokeWidth={2}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="benchmark"
                    stroke="#7dd3fc"
                    strokeWidth={1.5}
                    strokeDasharray="4 3"
                    dot={false}
                  />
                </ComposedChart>
              </ChartContainer>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-foreground text-base">Risk-adjusted performance</CardTitle>
              </CardHeader>
              <CardContent>
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border text-xs text-muted-foreground">
                      <th className="text-left pb-2 font-medium">Metric</th>
                      <th className="text-right pb-2 pr-4 font-medium">Strategy</th>
                      <th className="text-right pb-2 font-medium">Buy &amp; hold</th>
                    </tr>
                  </thead>
                  <tbody>
                    <MetricRow label="Total return" strategy={result.strategy_metrics.total_return_pct} benchmark={result.benchmark_metrics.total_return_pct} suffix="%" />
                    <MetricRow label="CAGR" strategy={result.strategy_metrics.cagr_pct} benchmark={result.benchmark_metrics.cagr_pct} suffix="%" />
                    <MetricRow label="Sharpe ratio" strategy={result.strategy_metrics.sharpe_ratio} benchmark={result.benchmark_metrics.sharpe_ratio} />
                    <MetricRow label="Sortino ratio" strategy={result.strategy_metrics.sortino_ratio} benchmark={result.benchmark_metrics.sortino_ratio} />
                    <MetricRow label="Max drawdown" strategy={result.strategy_metrics.max_drawdown_pct} benchmark={result.benchmark_metrics.max_drawdown_pct} suffix="%" higherIsBetter={true} />
                    <MetricRow label="Calmar ratio" strategy={result.strategy_metrics.calmar_ratio} benchmark={result.benchmark_metrics.calmar_ratio} />
                    <MetricRow label="Win rate" strategy={result.strategy_metrics.win_rate_pct} benchmark={result.benchmark_metrics.win_rate_pct} suffix="%" />
                    <MetricRow label="Trades" strategy={result.strategy_metrics.num_trades} benchmark={result.benchmark_metrics.num_trades} />
                    <MetricRow label="Profit factor" strategy={result.strategy_metrics.profit_factor} benchmark={result.benchmark_metrics.profit_factor} />
                  </tbody>
                </table>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-foreground text-base">Trade log</CardTitle>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                {result.trades.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-6 text-center">
                    No trades — the model never signalled a position change over this window.
                  </p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted-foreground border-b border-border">
                        <th className="pb-2 pr-3 font-medium">Entry</th>
                        <th className="pb-2 pr-3 font-medium">Exit</th>
                        <th className="pb-2 text-right font-medium">P&amp;L</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.map((t, i) => (
                        <tr key={i} className="border-b border-border/60 last:border-0">
                          <td className="py-2 pr-3 text-muted-foreground">
                            {t.entry_date} @ ₹{t.entry_price.toFixed(2)}
                          </td>
                          <td className="py-2 pr-3 text-muted-foreground">
                            {t.exit_date ? `${t.exit_date} @ ₹${t.exit_price?.toFixed(2)}` : "open"}
                          </td>
                          <td
                            className={`py-2 text-right tabular font-medium flex items-center justify-end gap-1 ${
                              (t.pnl_pct ?? 0) >= 0 ? "text-success" : "text-destructive"
                            }`}
                          >
                            {(t.pnl_pct ?? 0) >= 0 ? (
                              <TrendingUp className="h-3.5 w-3.5" />
                            ) : (
                              <TrendingDown className="h-3.5 w-3.5" />
                            )}
                            {t.pnl_pct?.toFixed(2)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>Model signals over this window:</span>
            {["BUY", "SELL", "HOLD"].map((s) => {
              const count = result.signals.filter((x) => x === s).length;
              return count > 0 ? (
                <Badge key={s} variant={BADGE_VARIANT[s]}>
                  {s} × {count}
                </Badge>
              ) : null;
            })}
          </div>
        </>
      )}
    </div>
  );
}
