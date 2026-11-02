"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

const pctKeys = /(move|pct|rate|ratio|return|drawdown|weight|top1|top3|vol|cagr|xirr|coverage|win_rate|drift|dd$|rank|spike|mom|ret_|above|high|hhi)/i;

const FRACTION_PARENTS = new Set(["drift", "sector_weights", "weights"]);
const FRACTION_KEYS = new Set(["loss_used_pct", "inflation", "shrink"]);

export function fmt(k: string, v: unknown, parent?: string): string {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "n/a";
    if ((parent && FRACTION_PARENTS.has(parent)) || FRACTION_KEYS.has(k)) return `${(v * 100).toFixed(1)}%`;
    const looksFraction = Math.abs(v) <= 5 && pctKeys.test(k) && !/_pct$|pct_/.test(k) && !/(hhi|ratio|rank|spike)/i.test(k);
    if (looksFraction) return `${(v * 100).toFixed(1)}%`;
    if (Math.abs(v) >= 1000) return v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
    return Number.isInteger(v) ? String(v) : v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  }
  return String(v);
}
const label = (k: string) => k.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function Stat({ k, v, tone, parent }: { k: string; v: unknown; tone?: "good" | "bad"; parent?: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card/60 px-3 py-2.5">
      <div className="truncate text-[11px] uppercase tracking-wide text-muted-foreground">{label(k)}</div>
      <div className={cn("font-num mt-0.5 truncate text-base font-semibold", tone === "good" && "text-success", tone === "bad" && "text-destructive")}>{fmt(k, v, parent)}</div>
    </div>
  );
}

export function Table({ rows, max = 60 }: { rows: Record<string, unknown>[]; max?: number }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">Nothing to show.</p>;
  const cols = Object.keys(rows[0]).filter((c) => typeof rows[0][c] !== "object" || rows[0][c] === null);
  return (
    <div className="max-w-full overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-max text-sm">
        <thead className="bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
          <tr>{cols.map((c) => <th key={c} className="px-3 py-2 font-medium">{label(c)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, max).map((r, i) => (
            <tr key={i} className="border-t border-border">
              {cols.map((c) => <td key={c} className="font-num whitespace-nowrap px-3 py-1.5">{fmt(c, r[c])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > max && <div className="border-t border-border px-3 py-1.5 text-xs text-muted-foreground">Showing {max} of {rows.length}</div>}
    </div>
  );
}

// Generic renderer: scalars become stat tiles, arrays of objects become tables, nested objects recurse.
export function Generic({ data, depth = 0, parent }: { data: unknown; depth?: number; parent?: string }) {
  if (Array.isArray(data)) {
    if (data.length && typeof data[0] === "object" && data[0] !== null && !Array.isArray(data[0])) return <Table rows={data as Record<string, unknown>[]} />;
    return <p className="font-num text-sm">{data.map((d) => (typeof d === "object" ? JSON.stringify(d) : String(d))).join(" · ") || "Nothing to show."}</p>;
  }
  if (data && typeof data === "object") {
    const e = Object.entries(data as Record<string, unknown>);
    const scalars = e.filter(([, v]) => v === null || typeof v !== "object");
    const rest = e.filter(([, v]) => v !== null && typeof v === "object" && !(Array.isArray(v) && v.length === 0));
    const notes = scalars.filter(([k, v]) => typeof v === "string" && (v as string).length > 40);
    const tiles = scalars.filter((x) => !notes.includes(x));
    return (
      <div className="space-y-4">
        {tiles.length > 0 && <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2">{tiles.map(([k, v]) => <Stat key={k} k={k} v={v} parent={parent} />)}</div>}
        {notes.map(([k, v]) => <p key={k} className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">{String(v)}</p>)}
        {rest.map(([k, v]) => (
          <section key={k}>
            <h3 className={cn("mb-2 font-medium text-muted-foreground", depth ? "text-xs" : "text-sm")}>{label(k)}</h3>
            <Generic data={v} depth={depth + 1} parent={k} />
          </section>
        ))}
      </div>
    );
  }
  return <p className="text-sm">{String(data)}</p>;
}

type Series = { name: string; color: string; pts: [number, number][] };
export function LineSvg({ series, zero, xfmt, height = 220 }: { series: Series[]; zero?: boolean; xfmt?: (x: number) => string; height?: number }) {
  const W = 700, H = height, pad = { l: 56, r: 12, t: 10, b: 24 };
  const all = series.flatMap((s) => s.pts);
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys, zero ? 0 : Infinity), y1 = Math.max(...ys, zero ? 0 : -Infinity);
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const X = (x: number) => pad.l + ((x - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r);
  const Y = (y: number) => pad.t + (1 - (y - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => y0 + t * (y1 - y0));
  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Chart">
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={pad.l} x2={W - pad.r} y1={Y(t)} y2={Y(t)} stroke="currentColor" opacity={0.1} />
            <text x={pad.l - 6} y={Y(t) + 3} textAnchor="end" fontSize="10" fill="currentColor" opacity={0.6}>{Math.abs(t) >= 1000 ? Math.round(t).toLocaleString("en-IN") : t.toFixed(2).replace(/\.?0+$/, "")}</text>
          </g>
        ))}
        {zero && y0 < 0 && y1 > 0 && <line x1={pad.l} x2={W - pad.r} y1={Y(0)} y2={Y(0)} stroke="currentColor" opacity={0.45} strokeDasharray="4 3" />}
        {series.map((s) => <polyline key={s.name} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" points={s.pts.map((p) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ")} />)}
        {xfmt && [x0, (x0 + x1) / 2, x1].map((x, i) => <text key={i} x={X(x)} y={H - 6} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"} fontSize="10" fill="currentColor" opacity={0.6}>{xfmt(x)}</text>)}
      </svg>
      {series.length > 1 && (
        <div className="mt-1 flex flex-wrap gap-4 text-xs text-muted-foreground">
          {series.map((s) => <span key={s.name} className="flex items-center gap-1.5"><i className="inline-block h-0.5 w-4" style={{ background: s.color }} />{s.name}</span>)}
        </div>
      )}
    </div>
  );
}
