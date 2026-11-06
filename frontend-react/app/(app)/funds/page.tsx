"use client";

import * as React from "react";
import { Trash2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { addFund, deleteFund, getFunds, getPerformance, importCas, searchSchemes, type FundsView, type Performance } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const inputCls = "h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30";
const inr = (n: number | null | undefined) => (n == null ? "—" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`);
const pct = (n: number | null | undefined) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`);
const tone = (n: number | null | undefined) => (n == null ? "" : n >= 0 ? "text-success" : "text-destructive");
const err = (e: unknown, f: string) => (e instanceof Error ? e.message : f);

export default function FundsPage() {
  const { token } = useAuth();
  const [view, setView] = React.useState<FundsView | null>(null);
  const [stocks, setStocks] = React.useState<Performance | null>(null);
  const [tick, setTick] = React.useState(0);
  const [loadErr, setLoadErr] = React.useState<string | null>(null);
  const refresh = () => setTick((t) => t + 1);

  React.useEffect(() => {
    if (!token) return;
    let live = true;
    getFunds(token).then((v) => { if (live) { setView(v); setLoadErr(null); } }).catch((e) => live && setLoadErr(err(e, "Could not load funds")));
    getPerformance(token).then((p) => live && setStocks(p)).catch(() => {});
    return () => { live = false; };
  }, [token, tick]);

  const stockValue = stocks?.real_prices ? stocks.total.value : null;
  const both = view && stockValue != null ? view.total.value + stockValue : null;

  return (
    <div className="min-w-0 space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Mutual funds</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Import your Consolidated Account Statement (CAS) or add funds by hand. Values use AMFI&apos;s published NAV, updated once a day.</p>
      </header>
      {loadErr && <p role="alert" className="text-sm text-destructive">{loadErr}</p>}
      {view?.nav_note && <p role="status" className="rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-sm text-warning">{view.nav_note}</p>}

      {view && view.funds.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base text-foreground">Your funds</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div><dt className="text-xs text-muted-foreground">Invested</dt><dd className="font-num text-xl font-semibold">{inr(view.total.invested)}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Value</dt><dd className="font-num text-xl font-semibold">{inr(view.total.value)}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Gain</dt><dd className={cn("font-num text-xl font-semibold", tone(view.total.gain))}>{inr(view.total.gain)}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Stocks + funds</dt><dd className="font-num text-xl font-semibold">{both == null ? "—" : inr(both)}</dd></div>
            </dl>
            {both == null && <p className="text-xs text-muted-foreground">The combined total appears when your stocks have real prices (Zerodha connected or NSE data loaded).</p>}
            <div className="max-w-full overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-max text-sm">
                <thead className="bg-muted/40 text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Fund</th><th className="px-3 py-2 text-right">Units</th><th className="px-3 py-2 text-right">NAV</th><th className="px-3 py-2 text-right">Invested</th><th className="px-3 py-2 text-right">Value</th><th className="px-3 py-2 text-right">XIRR</th><th className="px-3 py-2" /></tr></thead>
                <tbody className="font-num">
                  {view.funds.map((f) => (
                    <tr key={f.id} className="border-t border-border">
                      <td className="max-w-[18rem] px-3 py-2 font-sans"><div className="truncate font-medium" title={f.scheme_name}>{f.scheme_name}</div><div className="text-xs text-muted-foreground">{f.folio ? `Folio ${f.folio} · ` : ""}{f.source === "cas" ? "from CAS" : "added by hand"}</div></td>
                      <td className="px-3 py-2 text-right">{f.units}</td>
                      <td className="px-3 py-2 text-right" title={`${f.nav_source === "amfi" ? "AMFI" : "your statement"}, ${f.nav_date ?? ""}`}>{f.nav ?? "—"}</td>
                      <td className="px-3 py-2 text-right">{inr(f.invested)}</td>
                      <td className={cn("px-3 py-2 text-right", tone(f.gain))}>{inr(f.value)}</td>
                      <td className={cn("px-3 py-2 text-right", tone(f.xirr))}>{pct(f.xirr)}</td>
                      <td className="px-3 py-2 text-right"><button aria-label={`Remove ${f.scheme_name}`} className="text-muted-foreground hover:text-destructive" onClick={async () => { await deleteFund(token!, f.id); refresh(); }}><Trash2 className="h-3.5 w-3.5" /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-muted-foreground">XIRR needs the purchase history and at least a year of it; statements without transactions (NSDL/CDSL) show a plain gain.</p>
          </CardContent>
        </Card>
      )}
      {view && view.funds.length === 0 && <p className="text-sm text-muted-foreground">No funds yet. Import your CAS statement below, or add a fund by hand.</p>}

      {token && <div className="grid min-w-0 gap-6 lg:grid-cols-2"><ImportCas token={token} onDone={refresh} /><AddManual token={token} onDone={refresh} /></div>}
    </div>
  );
}

function ImportCas({ token, onDone }: { token: string; onDone: () => void }) {
  const [file, setFile] = React.useState<File | null>(null);
  const [pw, setPw] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);
  const go = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setNote(null);
    try { const r = await importCas(token, file, pw); setNote({ ok: true, text: [r.message, ...r.notes].join(" ") }); setPw(""); onDone(); }
    catch (e) { setNote({ ok: false, text: err(e, "Import failed") }); }
    finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Import a CAS statement</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={go} className="space-y-3 text-sm">
          <p className="text-muted-foreground">Request a detailed CAS from CAMS (camsonline.com) or KFintech; it arrives by email as a locked PDF. NSDL and CDSL statements work too. Importing again replaces the funds from the last import.</p>
          <div className="space-y-1"><label htmlFor="cas-file" className="text-xs text-muted-foreground">CAS PDF</label>
            <input id="cas-file" required type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-2" /></div>
          <div className="space-y-1"><label htmlFor="cas-pw" className="text-xs text-muted-foreground">PDF password</label>
            <input id="cas-pw" required type="password" autoComplete="off" value={pw} onChange={(e) => setPw(e.target.value)} className={inputCls} /></div>
          <Button type="submit" disabled={busy || !file}>{busy ? "Reading…" : "Import"}</Button>
          <p className="text-xs text-muted-foreground">The password opens the file on the server and is not stored.</p>
          {note && <p role="status" className={note.ok ? "text-success" : "text-destructive"}>{note.text}</p>}
        </form>
      </CardContent>
    </Card>
  );
}

function AddManual({ token, onDone }: { token: string; onDone: () => void }) {
  const [q, setQ] = React.useState("");
  const [hits, setHits] = React.useState<{ scheme_code: string; name: string; nav: number }[]>([]);
  const [pick, setPick] = React.useState<{ scheme_code: string; name: string } | null>(null);
  const [units, setUnits] = React.useState("");
  const [inv, setInv] = React.useState("");
  const [d, setD] = React.useState("");
  const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);
  const find = async () => {
    setNote(null);
    try { const r = await searchSchemes(token, q); setHits(r.schemes); if (!r.schemes.length) setNote({ ok: false, text: "No AMFI scheme matches. Try fewer words." }); }
    catch (e) { setNote({ ok: false, text: err(e, "Search failed") }); }
  };
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pick) return;
    try { await addFund(token, { scheme_code: pick.scheme_code, units: Number(units), invested: Number(inv), date: d }); setNote({ ok: true, text: `Added ${pick.name}.` }); setPick(null); setHits([]); setUnits(""); setInv(""); onDone(); }
    catch (e) { setNote({ ok: false, text: err(e, "Not added") }); }
  };
  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Add a fund by hand</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex gap-2">
          <input aria-label="Fund name" placeholder="parag parikh flexi direct growth" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); find(); } }} className={inputCls} />
          <Button type="button" variant="outline" onClick={find} disabled={q.trim().length < 3}>Search</Button>
        </div>
        {hits.length > 0 && !pick && (
          <ul className="max-h-56 space-y-1 overflow-y-auto">{hits.map((h) => (
            <li key={h.scheme_code}><button type="button" onClick={() => setPick(h)} className="w-full rounded-md px-2 py-1.5 text-left hover:bg-accent">{h.name} <span className="font-num text-xs text-muted-foreground">NAV {h.nav}</span></button></li>))}</ul>
        )}
        {pick && (
          <form onSubmit={save} className="grid gap-3 sm:grid-cols-3">
            <p className="sm:col-span-3"><span className="font-medium">{pick.name}</span> <button type="button" className="text-xs text-primary" onClick={() => setPick(null)}>change</button></p>
            <div className="space-y-1"><label htmlFor="mf-u" className="text-xs text-muted-foreground">Units</label><input id="mf-u" required type="number" step="any" min={0.001} inputMode="decimal" value={units} onChange={(e) => setUnits(e.target.value)} className={inputCls} /></div>
            <div className="space-y-1"><label htmlFor="mf-i" className="text-xs text-muted-foreground">Amount invested (₹)</label><input id="mf-i" required type="number" step="any" min={1} inputMode="decimal" value={inv} onChange={(e) => setInv(e.target.value)} className={inputCls} /></div>
            <div className="space-y-1"><label htmlFor="mf-d" className="text-xs text-muted-foreground">Date</label><input id="mf-d" required type="date" value={d} onChange={(e) => setD(e.target.value)} className={inputCls} /></div>
            <div className="sm:col-span-3"><Button type="submit">Add fund</Button></div>
          </form>
        )}
        {note && <p role="status" className={note.ok ? "text-success" : "text-destructive"}>{note.text}</p>}
      </CardContent>
    </Card>
  );
}
