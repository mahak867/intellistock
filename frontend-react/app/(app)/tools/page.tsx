"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { TOOLS, type Tool } from "@/lib/tools";
import { Generic, LineSvg, SourceBanner, Stat, Table } from "@/components/tools/result";
import { cn } from "@/lib/utils";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api/v1";
type Vals = Record<string, string>;
const initial = (t: Tool): Vals => Object.fromEntries(t.fields.map((f) => [f.name, f.def ?? ""]));
const inputCls = "font-num h-9 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30";

function Checklist({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [items, setItems] = React.useState<{ text: string; required: boolean }[]>([]);
  const { token } = useAuth();
  React.useEffect(() => {
    fetch(`${API}/tools/risk/checklist-items`, { headers: token && token !== "demo" ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.json()).then(setItems).catch(() => setItems([]));
  }, [token]);
  const ans: Record<string, boolean> = JSON.parse(value || "{}");
  return (
    <div className="space-y-2">
      {items.map((i) => (
        <label key={i.text} className="flex min-w-0 cursor-pointer items-start gap-3 rounded-lg border border-border bg-card/60 px-3 py-2.5 text-sm">
          <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--primary)]" checked={!!ans[i.text]}
            onChange={(e) => onChange(JSON.stringify({ ...ans, [i.text]: e.target.checked }))} />
          <span className="min-w-0">{i.text}{!i.required && <span className="ml-2 text-xs text-muted-foreground">optional</span>}</span>
        </label>
      ))}
      {!items.length && <p className="text-sm text-muted-foreground">Could not load the checklist. Is the API running?</p>}
    </div>
  );
}

function ToolView({ tool, data }: { tool: Tool; data: any }) {
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
  if (tool.view === "payoff") {
    const pts = data.x.map((x: number, i: number) => [x, data.pnl[i]] as [number, number]);
    return (
      <div className="space-y-4">
        <LineSvg zero series={[{ name: "Profit or loss at expiry", color: "var(--primary)", pts }]} xfmt={(x) => Math.round(x).toLocaleString("en-IN")} />
        <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2">
          <Stat k="Max profit" v={data.max_profit ?? "Unlimited"} tone="good" />
          <Stat k="Max loss" v={data.max_loss ?? "Unlimited"} tone="bad" />
          <Stat k="Net premium" v={data.net_premium} />
          <Stat k="Break-evens" v={data.breakevens.map((b: number) => Math.round(b).toLocaleString("en-IN")).join(", ") || "none"} />
        </div>
        <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">{data.note}</p>
      </div>
    );
  }
  if (tool.view === "backtest") {
    const eq = data.equity as { time: string; strategy: number; hold: number }[];
    const w = data.walk_forward_out_of_sample, ins = data.in_sample, h = data.buy_and_hold, d = data.worst_case_drawdown;
    return (
      <div className="space-y-5">
        <SourceBanner data={data} />
        <LineSvg series={[
          { name: "Strategy, full history (in-sample)", color: "var(--primary)", pts: eq.map((p, i) => [i, p.strategy]) },
          { name: "Buy and hold", color: "var(--muted-foreground)", pts: eq.map((p, i) => [i, p.hold]) },
        ]} xfmt={(i) => eq[Math.min(Math.round(i), eq.length - 1)]?.time ?? ""} />
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-max text-sm">
            <thead className="bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground"><tr><th className="px-3 py-2">Result</th><th className="px-3 py-2">Return</th><th className="px-3 py-2">Sharpe</th><th className="px-3 py-2">Max drawdown</th><th className="px-3 py-2">Trades</th></tr></thead>
            <tbody className="font-num">
              {[["Out-of-sample (believe this)", w], ["In-sample (flattering)", ins], ["Buy and hold", h]].map(([n, m]: any) => (
                <tr key={n} className="border-t border-border"><td className="px-3 py-2 font-sans">{n}</td><td className="px-3 py-2">{pct(m.total_return)}</td><td className="px-3 py-2">{m.sharpe.toFixed(2)}</td><td className="px-3 py-2">{pct(m.max_drawdown)}</td><td className="px-3 py-2">{m.trades}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-medium text-muted-foreground">Worst-case drawdown, reshuffled by luck alone</h3>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2">
            <Stat k="Typical worst drawdown" v={pct(d.median_max_dd)} /><Stat k="1 in 20 is worse than" v={pct(d.p95_worst_dd)} tone="bad" />
            <Stat k="1 in 100 is worse than" v={pct(d.p99_worst_dd)} tone="bad" /><Stat k={`Chance of losing ${Math.abs(d.ruin_level * 100)}%`} v={pct(d.prob_dd_beyond_ruin)} />
          </div>
        </div>
      </div>
    );
  }
  if (tool.view === "screener") return <Screener data={data} />;
  if (tool.view === "portrisk") {
    const a = data.allocation, m = Object.keys(data.correlation.matrix);
    return (
      <div className="space-y-5">
        <SourceBanner data={data} />
        <div className="grid gap-3 sm:grid-cols-2">
          {(["week", "month"] as const).map((k) => (
            <div key={k} className="rounded-xl border border-border bg-card/60 p-4">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">{k === "week" ? "One week" : "One month"}, 95% of the time you lose less than</div>
              <div className="font-num mt-1 text-2xl font-semibold text-destructive">₹{Math.round(Math.max(data[k].parametric.var_amount, data[k].historical.var_amount)).toLocaleString("en-IN")}</div>
              <div className="mt-1 text-xs text-muted-foreground">Model: {pct(data[k].parametric.var_pct)} · History: {pct(data[k].historical.var_pct)}. The larger of the two is shown.</div>
            </div>
          ))}
        </div>
        <section><h3 className="mb-2 text-sm font-medium text-muted-foreground">Crash scenarios</h3><Table rows={data.stress} /></section>
        <section><h3 className="mb-2 text-sm font-medium text-muted-foreground">Holdings</h3><Table rows={a.positions} /></section>
        <section>
          <h3 className="mb-2 text-sm font-medium text-muted-foreground">Correlation (1 = move together)</h3>
          <div className="max-w-full overflow-x-auto"><table className="font-num text-xs"><tbody>
            <tr><td />{m.map((c) => <td key={c} className="px-2 py-1 text-muted-foreground">{c}</td>)}</tr>
            {m.map((r) => <tr key={r}><td className="pr-2 text-muted-foreground">{r}</td>{m.map((c) => { const v = data.correlation.matrix[r][c]; return <td key={c} className="px-2 py-1 text-center" style={{ background: `color-mix(in srgb, var(--primary) ${Math.round(Math.abs(v) * 70)}%, transparent)` }}>{v.toFixed(2)}</td>; })}</tr>)}
          </tbody></table></div>
        </section>
      </div>
    );
  }
  // Tool-specific summaries on top of the generic renderer
  if (tool.id === "check") return <div className={cn("rounded-xl border p-4 text-sm", data.pass ? "border-success/50" : "border-destructive/50")}><div className={cn("font-display text-xl font-semibold", data.pass ? "text-success" : "text-destructive")}>{data.pass ? "Clear to trade" : "Do not enter yet"}</div>{[...data.blocking, ...data.warnings].map((t: string) => <div key={t} className="mt-1 text-muted-foreground">{data.blocking.includes(t) ? "Blocking" : "Warning"}: {t}</div>)}</div>;
  if (tool.id === "day") return <div className="space-y-3"><div className={cn("font-display text-xl font-semibold", data.level === "stop" ? "text-destructive" : data.level === "warn" ? "text-warning" : "text-success")}>{data.level === "stop" ? "Stop trading today" : data.level === "warn" ? "Slow down" : "Within limits"}</div><Generic data={data} /></div>;
  return <Generic data={data} />;
}

function Screener({ data }: { data: { rows: Record<string, unknown>[]; synthetic: boolean; as_of: string; universe: number } }) {
  const rows = data.rows;
  const [f, setF] = React.useState<"all" | "mom" | "quiet" | "spike">("all");
  const filtered = rows.filter((r) => f === "all" || (f === "mom" && (r.mom_rank as number) >= 0.8) || (f === "quiet" && (r.vol_pct_rank as number) <= 0.2) || (f === "spike" && (r.volume_spike as number) >= 1.5));
  const shown = [...filtered].sort((a, b) => ((b.mom_rank as number) ?? 0) - ((a.mom_rank as number) ?? 0));
  return (
    <div className="space-y-3">
      <SourceBanner data={data} />
      <p className="text-xs text-muted-foreground">{data.universe} most liquid stocks. Rank columns run 0 to 1 (1 = strongest).</p>
      <div role="group" aria-label="Filter" className="flex flex-wrap gap-1.5 text-xs">
        {([["all", "All"], ["mom", "Top momentum"], ["quiet", "Unusually quiet"], ["spike", "Volume spike"]] as const).map(([k, l]) => (
          <button key={k} aria-pressed={f === k} onClick={() => setF(k)} className={cn("rounded-md border px-2.5 py-1.5 font-medium transition-colors", f === k ? "border-primary/50 bg-primary/15 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{l}</button>
        ))}
      </div>
      <Table rows={shown} />
    </div>
  );
}

function ToolsInner() {
  const { token } = useAuth();
  const params = useSearchParams();
  const first = TOOLS.find((t) => t.id === params.get("tool"))?.id ?? "size";
  const [id, setId] = React.useState(first);
  const tool = TOOLS.find((t) => t.id === id)!;
  const [vals, setVals] = React.useState<Vals>(() => initial(TOOLS.find((t) => t.id === first)!));
  const [data, setData] = React.useState<any>(null);
  const [err, setErr] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const pick = (t: Tool) => { setId(t.id); setVals(initial(t)); setData(null); setErr(""); };

  const run = React.useCallback(async (t: Tool, v: Vals) => {
    setBusy(true); setErr("");
    try {
      const path = t.pathFor ? t.pathFor(v) : t.path;
      const body = t.method === "POST" ? JSON.stringify(t.build(v)) : undefined;
      const r = await fetch(`${API}${path}`, {
        method: t.method, body,
        headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(token && token !== "demo" ? { Authorization: `Bearer ${token}` } : {}) },
      });
      const j = await r.json().catch(() => null);
      if (!r.ok) {
        const d = j?.detail;
        throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x: any) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("; ") : `Request failed (${r.status})`);
      }
      setData(j);
    } catch (e: any) {
      setData(null);
      setErr(e instanceof TypeError ? "Cannot reach the API. Start the backend and check NEXT_PUBLIC_API_BASE." : e.message);
    } finally { setBusy(false); }
  }, [token]);

  React.useEffect(() => { if (tool.method === "GET" && tool.fields.length === 0) run(tool, vals); }, [tool, run]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="min-w-0 space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Tools</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Calculators for the decisions that cost real money: how much to buy, what it really costs, what could go wrong. Nothing here predicts prices.</p>
      </header>
      <div className="grid min-w-0 gap-6 lg:grid-cols-[230px_minmax(0,1fr)]">
        <nav aria-label="Tools" className="min-w-0 space-y-4">
          {(["Trader", "Investor"] as const).map((g) => (
            <div key={g}>
              <div className="mb-1.5 px-1 text-[11px] uppercase tracking-wider text-muted-foreground">{g}</div>
              <div className="flex gap-1.5 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
                {TOOLS.filter((t) => t.group === g).map((t) => (
                  <button key={t.id} onClick={() => pick(t)} aria-current={t.id === id ? "page" : undefined}
                    className={cn("shrink-0 rounded-lg px-3 py-2 text-left text-sm transition-colors duration-150 focus-visible:outline-2 outline-primary",
                      t.id === id ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground")}>
                    {t.title}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <section className="min-w-0 space-y-5" aria-live="polite">
          <div>
            <h2 className="font-display text-xl font-semibold">{tool.title}</h2>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{tool.blurb}</p>
          </div>
          {tool.fields.length > 0 && (
            <form className="grid min-w-0 gap-3 rounded-xl border border-border bg-card/40 p-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); run(tool, vals); }}>
              {tool.fields.map((f) => (
                <div key={f.name} className={cn("min-w-0 space-y-1", (f.type === "textarea" || f.type === "checks") && "sm:col-span-2")}>
                  <label htmlFor={`f-${f.name}`} className="text-xs text-muted-foreground">{f.label}{f.hint && <span className="ml-1 opacity-70">({f.hint})</span>}</label>
                  {f.type === "textarea" ? (
                    <textarea id={`f-${f.name}`} rows={f.rows ?? 5} value={vals[f.name] ?? ""} onChange={(e) => setVals({ ...vals, [f.name]: e.target.value })} className={cn(inputCls, "h-auto py-2 leading-relaxed")} spellCheck={false} />
                  ) : f.type === "select" ? (
                    <select id={`f-${f.name}`} value={vals[f.name]} onChange={(e) => setVals({ ...vals, [f.name]: e.target.value })} className={inputCls}>{f.options!.map((o) => <option key={o}>{o}</option>)}</select>
                  ) : f.type === "checks" ? (
                    <Checklist value={vals[f.name] ?? ""} onChange={(v) => setVals({ ...vals, [f.name]: v })} />
                  ) : (
                    <input id={`f-${f.name}`} type={f.type === "number" ? "number" : "text"} step="any" inputMode={f.type === "number" ? "decimal" : undefined} value={vals[f.name] ?? ""} onChange={(e) => setVals({ ...vals, [f.name]: e.target.value })} className={inputCls} />
                  )}
                </div>
              ))}
              <div className="sm:col-span-2">
                <button type="submit" disabled={busy} className="h-9 rounded-lg bg-primary px-5 text-sm font-medium text-primary-foreground transition-[transform,opacity] duration-150 active:scale-[0.97] disabled:opacity-60 focus-visible:outline-2 outline-offset-2 outline-primary">{busy ? "Working…" : "Calculate"}</button>
              </div>
            </form>
          )}
          {err && <div role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</div>}
          {busy && !data && tool.fields.length === 0 && <p className="text-sm text-muted-foreground">Loading…</p>}
          {data && <div className="min-w-0 rounded-xl border border-border bg-card/40 p-4"><ToolView tool={tool} data={data} /></div>}
        </section>
      </div>
    </div>
  );
}

export default function ToolsPage() {
  return <React.Suspense fallback={null}><ToolsInner /></React.Suspense>;
}
