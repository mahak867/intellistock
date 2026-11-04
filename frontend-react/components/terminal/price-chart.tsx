"use client";

import * as React from "react";
import {
  createChart, CandlestickSeries, LineSeries, HistogramSeries, ColorType, CrosshairMode,
  type IChartApi, type Time,
} from "lightweight-charts"; // Apache-2.0, TradingView
import { sma, type Candle, type FanPoint } from "@/lib/demo";

const UP = "#45bfa6", DOWN = "#ee7167", VIOLET = "#8b88f0", MUTED = "#8a8a9c", GRID = "#1a1a24";

export type Hover = Candle | null;

export function PriceChart({
  candles, fan, showMA, showFan, onHover,
}: { candles: Candle[]; fan: FanPoint[]; showMA: boolean; showFan: boolean; onHover?: (c: Hover) => void }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const hoverRef = React.useRef(onHover);
  React.useEffect(() => { hoverRef.current = onHover; });

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart: IChartApi = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: MUTED, fontFamily: "IBM Plex Mono, monospace", fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: GRID }, horzLines: { color: GRID } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: "#4a4a60", labelBackgroundColor: "#2a2a3a" }, horzLine: { color: "#4a4a60", labelBackgroundColor: "#2a2a3a" } },
      rightPriceScale: { borderColor: "#23232f", scaleMargins: { top: 0.06, bottom: 0.25 } },
      timeScale: { borderColor: "#23232f", rightOffset: 14, timeVisible: false },
    });

    const price = chart.addSeries(CandlestickSeries, {
      upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
    });
    price.setData(candles as never);

    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(candles.map((c) => ({ time: c.time as Time, value: c.volume, color: c.close >= c.open ? "#45bfa633" : "#ee716733" })));

    if (showMA) {
      chart.addSeries(LineSeries, { color: "#e6b450", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
        .setData(sma(candles, 20) as never);
      chart.addSeries(LineSeries, { color: "#7dd3fc", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
        .setData(sma(candles, 50) as never);
    }

    if (showFan && fan.length) {
      const last = candles[candles.length - 1];
      const edge = (k: "hi" | "lo") => [{ time: last.time, value: last.close }, ...fan.map((f) => ({ time: f.time, value: f[k] }))];
      const opts = { priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
      chart.addSeries(LineSeries, { ...opts, color: VIOLET + "66", lineWidth: 1, lineStyle: 2 }).setData(edge("hi") as never);
      chart.addSeries(LineSeries, { ...opts, color: VIOLET + "66", lineWidth: 1, lineStyle: 2 }).setData(edge("lo") as never);
      chart.addSeries(LineSeries, { ...opts, color: VIOLET, lineWidth: 3, lastValueVisible: true })
        .setData([{ time: last.time, value: last.close }, ...fan.map((f) => ({ time: f.time, value: f.mean }))] as never);
    }

    const byTime = new Map(candles.map((c) => [c.time, c]));
    chart.subscribeCrosshairMove((p) => hoverRef.current?.(p.time ? byTime.get(p.time as string) ?? null : null));
    chart.timeScale().setVisibleLogicalRange({ from: candles.length - 130, to: candles.length + (showFan ? fan.length + 6 : 8) });
    return () => chart.remove();
  }, [candles, fan, showMA, showFan]);

  return <div ref={ref} className="h-full w-full" role="img" aria-label="Candlestick price chart with forecast" />;
}
