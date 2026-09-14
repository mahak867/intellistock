"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import {
  ComposedChart,
  Line,
  Area,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { ArrowUpRight, ArrowDownRight, Minus, ChevronDown } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import {
  getPrediction,
  getOhlcv,
  type PredictionResponse,
  type OHLCVResponse,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/registry/bases/radix/ui/chart";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";

const priceChartConfig = {
  close: { label: "Historical", color: "var(--chart-3)" },
  forecast: { label: "LSTM forecast", color: "var(--chart-1)" },
} satisfies ChartConfig;

const volumeChartConfig = {
  volume: { label: "Volume", color: "var(--chart-4)" },
} satisfies ChartConfig;

const rsiChartConfig = {
  rsi: { label: "RSI", color: "var(--chart-4)" },
} satisfies ChartConfig;


const HORIZONS = [1, 3, 5, 7, 14, 30];

export default function PredictionsPage() {
  const { token } = useAuth();
  const params = useSearchParams();

  const [ticker, setTicker] = React.useState(params.get("ticker") || "RELIANCE");
  const [horizon, setHorizon] = React.useState(5);
  const [prediction, setPrediction] = React.useState<PredictionResponse | null>(null);
  const [ohlcv, setOhlcv] = React.useState<OHLCVResponse | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [metricsOpen, setMetricsOpen] = React.useState(false);

  const runPrediction = React.useCallback(
    async (t: string, h: number) => {
      if (!token || !t) return;
      setLoading(true);
      setError(null);
      try {
        const [pred, hist] = await Promise.all([
          getPrediction(token, t, h),
          getOhlcv(token, t, 180),
        ]);
        setPrediction(pred);
        setOhlcv(hist);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not load predictions");
        setPrediction(null);
      } finally {
        setLoading(false);
      }
    },
    [token]
  );

  React.useEffect(() => {
    runPrediction(ticker, horizon);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const chartData = React.useMemo(() => {
    if (!ohlcv) return [];
    const hist = ohlcv.data.map((row) => ({
      date: String(row.date),
      close: Number(row.Close),
      volume: Number(row.Volume),
      rsi: row.RSI != null ? Number(row.RSI) : undefined,
    }));
    const forecast = (prediction?.predictions || []).map((p) => ({
      date: p.date,
      forecast: p.predicted_close,
      band: [p.lower_bound, p.upper_bound] as [number, number],
    }));
    return [...hist, ...forecast];
  }, [ohlcv, prediction]);

  return (
    <div>
      <h1 className="font-display text-2xl font-semibold mb-6">Price predictions</h1>

      <div className="flex flex-wrap items-end gap-3 mb-6">
        <div className="flex-1 min-w-[220px] max-w-xs">
          <label className="text-xs font-medium text-muted-foreground mb-1.5 block">NSE ticker</label>
          <Input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="e.g. RELIANCE, TCS, INFY"
            onKeyDown={(e) => e.key === "Enter" && runPrediction(ticker, horizon)}
          />
        </div>
        <div className="w-32">
          <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Horizon</label>
          <Select
            value={String(horizon)}
            onValueChange={(v) => {
              const h = Number(v);
              setHorizon(h);
              runPrediction(ticker, h);
            }}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {HORIZONS.map((h) => (
                <SelectItem key={h} value={String(h)}>
                  {h} day{h > 1 ? "s" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button onClick={() => runPrediction(ticker, horizon)} disabled={loading}>
          {loading ? "Running…" : "Predict →"}
        </Button>
      </div>

      {error && (
        <Card className="mb-6 border-destructive/30">
          <CardContent className="py-4 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      {prediction && (
        <>
          <SignalRow prediction={prediction} />

          <Card className="mt-6">
            <CardHeader>
              <CardTitle className="text-foreground text-base flex items-center gap-2">
                Price &amp; forecast
                <Badge
                  variant={prediction.signal.predicted_return_pct >= 0 ? "success-light" : "destructive-light"}
                >
                  {prediction.signal.predicted_return_pct >= 0 ? (
                    <ArrowUpRight aria-hidden="true" />
                  ) : (
                    <ArrowDownRight aria-hidden="true" />
                  )}
                  {prediction.signal.predicted_return_pct >= 0 ? "+" : ""}
                  {prediction.signal.predicted_return_pct.toFixed(2)}%
                </Badge>
              </CardTitle>
              <CardDescription>
                {ticker} · historical close vs. {horizon}-day LSTM forecast
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer config={priceChartConfig} className="h-[320px] w-full">
                <ComposedChart data={chartData} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
                  <defs>
                    <linearGradient id="fillClose" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--color-close)" stopOpacity={0.35} />
                      <stop offset="95%" stopColor="var(--color-close)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} />
                  <XAxis
                    dataKey="date"
                    tickLine={false}
                    axisLine={false}
                    tickMargin={8}
                    interval={Math.floor(chartData.length / 6)}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    width={56}
                    domain={["auto", "auto"]}
                  />
                  <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
                  <Area
                    type="monotone"
                    dataKey="close"
                    stroke="var(--color-close)"
                    fill="url(#fillClose)"
                    strokeWidth={1.75}
                    dot={false}
                    name="Historical"
                  />
                  <Line
                    type="monotone"
                    dataKey="forecast"
                    stroke="var(--color-forecast)"
                    strokeWidth={2}
                    strokeDasharray="4 3"
                    dot={{ r: 3, fill: "var(--color-forecast)" }}
                    name="LSTM forecast"
                  />
                </ComposedChart>
              </ChartContainer>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-foreground text-sm">Volume</CardTitle>
              </CardHeader>
              <CardContent>
                <ChartContainer config={volumeChartConfig} className="h-[140px] w-full">
                  <ComposedChart data={chartData}>
                    <XAxis dataKey="date" hide />
                    <YAxis hide />
                    <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
                    <Bar dataKey="volume" fill="var(--color-volume)" radius={[2, 2, 0, 0]} />
                  </ComposedChart>
                </ChartContainer>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-foreground text-sm">RSI (14)</CardTitle>
              </CardHeader>
              <CardContent>
                <ChartContainer config={rsiChartConfig} className="h-[140px] w-full">
                  <ComposedChart data={chartData}>
                    <XAxis dataKey="date" hide />
                    <YAxis domain={[0, 100]} hide />
                    <ReferenceLine y={70} stroke="var(--destructive)" strokeDasharray="3 3" />
                    <ReferenceLine y={30} stroke="var(--success)" strokeDasharray="3 3" />
                    <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
                    <Line type="monotone" dataKey="rsi" stroke="var(--color-rsi)" strokeWidth={1.5} dot={false} />
                  </ComposedChart>
                </ChartContainer>
              </CardContent>
            </Card>
          </div>

          <Card className="mt-4">
            <button
              className="w-full flex items-center justify-between px-5 py-4 text-left"
              onClick={() => setMetricsOpen((v) => !v)}
            >
              <span className="font-display text-sm font-medium text-muted-foreground">
                Model performance metrics
              </span>
              <ChevronDown
                className={`h-4 w-4 text-muted-foreground transition-transform ${metricsOpen ? "rotate-180" : ""}`}
              />
            </button>
            {metricsOpen && (
              <CardContent className="pt-0 pb-5 grid grid-cols-2 sm:grid-cols-4 gap-4">
                <Metric label="RMSE (₹)" value={prediction.metrics.RMSE?.toFixed(2)} />
                <Metric label="MAE (₹)" value={prediction.metrics.MAE?.toFixed(2)} />
                <Metric label="MAPE" value={`${prediction.metrics.MAPE?.toFixed(2)}%`} />
                <Metric
                  label="Directional accuracy"
                  value={`${prediction.metrics.Directional_Accuracy?.toFixed(1)}%`}
                />
              </CardContent>
            )}
          </Card>

          {prediction.cached && (
            <p className="mt-3 text-xs text-muted-foreground-2">⚡ Served from cache</p>
          )}
        </>
      )}
    </div>
  );
}

function SignalRow({ prediction }: { prediction: PredictionResponse }) {
  const { signal } = prediction;
  const map = {
    BUY: { cls: "success-light" as const, Icon: ArrowUpRight },
    SELL: { cls: "destructive-light" as const, Icon: ArrowDownRight },
    HOLD: { cls: "warning-light" as const, Icon: Minus },
  };
  const { cls, Icon } = map[signal.signal];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card>
        <CardHeader className="pb-1">
          <CardTitle>Signal</CardTitle>
        </CardHeader>
        <CardContent>
          <Badge variant={cls} className="text-sm px-3 py-1.5">
            <Icon className="h-3.5 w-3.5" />
            {signal.signal}
          </Badge>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-1">
          <CardTitle>Confidence</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="tabular text-2xl font-semibold">{(signal.confidence * 100).toFixed(1)}%</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-1">
          <CardTitle>Current price</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="tabular text-2xl font-semibold">
            ₹{signal.current_price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-1">
          <CardTitle>Predicted (next day)</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="tabular text-2xl font-semibold">
            ₹{signal.predicted_price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
          </p>
          <p className={`tabular text-xs font-medium mt-0.5 ${signal.predicted_return_pct >= 0 ? "text-success" : "text-destructive"}`}>
            {signal.predicted_return_pct >= 0 ? "+" : ""}
            {signal.predicted_return_pct.toFixed(2)}%
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground-2">{label}</p>
      <p className="tabular text-lg font-semibold mt-0.5">{value ?? "—"}</p>
    </div>
  );
}
