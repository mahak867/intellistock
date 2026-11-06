"use client";

import * as React from "react";
import { Trash2 } from "lucide-react";
import { addCorpAction, deleteCorpAction, getCorpActions, getPerformance, lookupCorpActions, type CorpAction, type Performance } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const inputCls = "font-num h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30";
const inr = (n: number | null | undefined) => (n == null ? "—" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`);
const pct = (n: number | null | undefined) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`);
const tone = (n: number | null | undefined) => (n == null ? "" : n >= 0 ? "text-success" : "text-destructive");
const describe = (a: CorpAction) => a.kind === "dividend" ? `Dividend ₹${a.amount} per share` : a.kind === "bonus" ? `Bonus ${a.ratio_new}:${a.ratio_old}` : `Split, face value ₹${a.ratio_new} to ₹${a.ratio_old}`;

export function PerformanceCard({ token, tick }: { token: string; tick: number }) {
  const [p, setP] = React.useState<Performance | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  React.useEffect(() => {
    let live = true;
    getPerformance(token).then((r) => live && setP(r)).catch((e) => live && setErr(e instanceof Error ? e.message : "Could not load"));
    return () => { live = false; };
  }, [token, tick]);
  if (err) return <p className="text-sm text-destructive">{err}</p>;
  if (!p || !p.holdings.length) return null;
  const t = p.total;
  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Your return vs NIFTY 50</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {p.warning && <p role="status" className="rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-sm text-warning">{p.warning}</p>}
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div><dt className="text-xs text-muted-foreground">Your XIRR (a year)</dt><dd className={cn("font-num text-xl font-semibold", tone(t.xirr))}>{pct(t.xirr)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Same money in NIFTY 50</dt><dd className="font-num text-xl font-semibold">{pct(t.nifty_xirr)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Dividends received</dt><dd className="font-num text-xl font-semibold">{inr(t.dividends)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Gain incl. dividends</dt><dd className={cn("font-num text-xl font-semibold", tone(t.gain))}>{inr(t.gain)}</dd></div>
        </dl>
        {t.benchmark_note && <p className="text-xs text-muted-foreground">{t.benchmark_note}</p>}
        {t.xirr == null && <p className="text-xs text-muted-foreground">XIRR appears once your first holding is a year old; until then the plain return is the honest figure.</p>}
        <div className="max-w-full overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-max text-sm">
            <thead className="bg-muted/40 text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Stock</th><th className="px-3 py-2 text-right">Invested</th><th className="px-3 py-2 text-right">Value</th><th className="px-3 py-2 text-right">Dividends</th><th className="px-3 py-2 text-right">Return</th><th className="px-3 py-2 text-right">XIRR</th><th className="px-3 py-2 text-right">NIFTY XIRR</th></tr></thead>
            <tbody className="font-num">
              {p.holdings.map((h, i) => (
                <tr key={`${h.ticker}${i}`} className="border-t border-border" title={h.note ?? undefined}>
                  <td className="px-3 py-2 font-sans font-medium">{h.ticker}</td><td className="px-3 py-2 text-right">{inr(h.invested)}</td><td className="px-3 py-2 text-right">{inr(h.value)}</td>
                  <td className="px-3 py-2 text-right">{inr(h.dividends)}</td><td className={cn("px-3 py-2 text-right", tone(h.return_pct))}>{pct(h.return_pct)}</td>
                  <td className={cn("px-3 py-2 text-right", tone(h.xirr))}>{h.xirr == null ? (h.note ? "under 1 yr" : "—") : pct(h.xirr)}</td><td className="px-3 py-2 text-right">{pct(h.nifty_xirr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground">NIFTY XIRR: what the same rupees, on the same dates, would have earned in the index. Prices: {p.price_source === "zerodha-live" ? "live from Zerodha" : p.real_prices ? "latest close" : "placeholders"}.</p>
      </CardContent>
    </Card>
  );
}

const EMPTY: CorpAction = { ticker: "", kind: "dividend", ex_date: "", amount: null, ratio_new: null, ratio_old: null };

export function CorporateActions({ token, onChange }: { token: string; onChange: () => void }) {
  const [rows, setRows] = React.useState<CorpAction[]>([]);
  const [a, setA] = React.useState<CorpAction>(EMPTY);
  const [found, setFound] = React.useState<CorpAction[] | null>(null);
  const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    getCorpActions(token).then((r) => live && setRows(r.actions)).catch(() => {});
    return () => { live = false; };
  }, [token, tick]);
  const changed = () => { setTick((x) => x + 1); onChange(); };
  const save = async (x: CorpAction) => {
    setBusy(true); setNote(null);
    try { await addCorpAction(token, x); setNote({ ok: true, text: `Added: ${x.ticker.toUpperCase()} ${describe(x).toLowerCase()} on ${x.ex_date}.` }); changed(); return true; }
    catch (e) { setNote({ ok: false, text: e instanceof Error ? e.message : "Not added" }); return false; }
    finally { setBusy(false); }
  };
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const x = { ...a, ticker: a.ticker.trim().toUpperCase() };
    if (await save(x)) setA({ ...EMPTY, kind: a.kind });
  };
  const lookup = async () => {
    if (!a.ticker.trim()) { setNote({ ok: false, text: "Type a stock symbol first." }); return; }
    setBusy(true); setNote(null); setFound(null);
    try { const r = await lookupCorpActions(token, a.ticker.trim()); setFound(r.actions); if (!r.actions.length) setNote({ ok: true, text: "NSE lists no dividends, bonuses or splits for that symbol." }); }
    catch (e) { setNote({ ok: false, text: e instanceof Error ? e.message : "Lookup failed" }); }
    finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Dividends, bonuses and splits</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <p className="text-muted-foreground">Record them here and your share count, average price and returns include them. Holdings bought before the ex-date get them.</p>
        <form onSubmit={submit} className="grid min-w-0 gap-3 sm:grid-cols-5 sm:items-end">
          <div className="min-w-0 space-y-1"><label htmlFor="ca-t" className="text-xs text-muted-foreground">Stock</label>
            <input id="ca-t" required maxLength={20} autoCapitalize="characters" spellCheck={false} placeholder="TCS" value={a.ticker} onChange={(e) => setA({ ...a, ticker: e.target.value })} className={inputCls} /></div>
          <div className="min-w-0 space-y-1"><label htmlFor="ca-k" className="text-xs text-muted-foreground">What</label>
            <select id="ca-k" value={a.kind} onChange={(e) => setA({ ...EMPTY, ticker: a.ticker, ex_date: a.ex_date, kind: e.target.value as CorpAction["kind"] })} className={inputCls}>
              <option value="dividend">Dividend</option><option value="bonus">Bonus</option><option value="split">Split</option></select></div>
          <div className="min-w-0 space-y-1"><label htmlFor="ca-d" className="text-xs text-muted-foreground">Ex-date</label>
            <input id="ca-d" required type="date" value={a.ex_date} onChange={(e) => setA({ ...a, ex_date: e.target.value })} className={inputCls} /></div>
          {a.kind === "dividend" ? (
            <div className="min-w-0 space-y-1"><label htmlFor="ca-a" className="text-xs text-muted-foreground">₹ per share</label>
              <input id="ca-a" required type="number" inputMode="decimal" step="any" min={0.01} value={a.amount ?? ""} onChange={(e) => setA({ ...a, amount: e.target.value ? Number(e.target.value) : null })} className={inputCls} /></div>
          ) : (
            <div className="grid min-w-0 grid-cols-2 gap-2">
              <div className="min-w-0 space-y-1"><label htmlFor="ca-n" className="text-xs text-muted-foreground">{a.kind === "bonus" ? "New (a)" : "Old face value"}</label>
                <input id="ca-n" required type="number" inputMode="decimal" step="any" min={0.01} value={a.ratio_new ?? ""} onChange={(e) => setA({ ...a, ratio_new: e.target.value ? Number(e.target.value) : null })} className={inputCls} /></div>
              <div className="min-w-0 space-y-1"><label htmlFor="ca-o" className="text-xs text-muted-foreground">{a.kind === "bonus" ? "Held (b)" : "New face value"}</label>
                <input id="ca-o" required type="number" inputMode="decimal" step="any" min={0.01} value={a.ratio_old ?? ""} onChange={(e) => setA({ ...a, ratio_old: e.target.value ? Number(e.target.value) : null })} className={inputCls} /></div>
            </div>
          )}
          <div className="flex gap-2"><Button type="submit" disabled={busy} className="h-10">Add</Button><Button type="button" variant="outline" disabled={busy} onClick={lookup} className="h-10">Find on NSE</Button></div>
        </form>
        {note && <p role="status" className={note.ok ? "text-success" : "text-destructive"}>{note.text}</p>}
        {found && found.length > 0 && (
          <div className="space-y-2 rounded-lg border border-primary/40 bg-primary/5 p-3">
            <p className="text-xs text-muted-foreground">From NSE&apos;s website. Check each against the company&apos;s announcement, then add it.</p>
            <ul className="space-y-1">{found.map((f) => (
              <li key={`${f.kind}${f.ex_date}`} className="flex flex-wrap items-center gap-2">
                <span className="font-num">{f.ex_date}</span><span>{describe(f)}</span>
                <Button size="sm" variant="outline" disabled={busy || rows.some((r) => r.ticker === f.ticker && r.kind === f.kind && r.ex_date === f.ex_date)}
                  onClick={() => save({ ...f, source: "nse" })}>{rows.some((r) => r.ticker === f.ticker && r.kind === f.kind && r.ex_date === f.ex_date) ? "Added" : "Add"}</Button>
              </li>))}</ul>
          </div>
        )}
        {rows.length > 0 && (
          <ul className="space-y-1">{rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border px-3 py-2">
              <span className="font-num font-semibold">{r.ticker}</span><span>{describe(r)}</span><span className="font-num text-muted-foreground">ex {r.ex_date}</span>
              <button className="ml-auto text-muted-foreground hover:text-destructive" aria-label={`Remove ${r.ticker} ${r.kind} on ${r.ex_date}`}
                onClick={async () => { await deleteCorpAction(token, r.id!); changed(); }}><Trash2 className="h-3.5 w-3.5" /></button>
            </li>))}</ul>
        )}
      </CardContent>
    </Card>
  );
}
