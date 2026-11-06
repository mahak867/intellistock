"use client";

import * as React from "react";
import { Trash2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { addAsset, deleteAsset, getAssets, uploadAssetFile, type NetWorth, type OtherAssetRow } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AccountAggregator } from "@/components/portfolio/aa-link";

const inputCls = "h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30";
const inr = (n: number | null | undefined) => (n == null ? "—" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`);
const KIND_LABEL: Record<string, string> = { bank: "Bank balance", fd: "Fixed deposit", rd: "Recurring deposit", ppf: "PPF", epf: "EPF", nps: "NPS", bond: "Bonds", gold: "Gold", real_estate: "Property", other: "Other" };

type Note = { ok: boolean; text: string } | null;

export default function NetWorthPage() {
  const { token } = useAuth();
  const [rows, setRows] = React.useState<OtherAssetRow[] | null>(null);
  const [nw, setNw] = React.useState<NetWorth | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [tick, setTick] = React.useState(0);
  const refresh = () => setTick((t) => t + 1);
  React.useEffect(() => {
    if (!token) return;
    let live = true;
    getAssets(token).then((r) => { if (live) { setRows(r.assets); setNw(r.net_worth); setErr(null); } }).catch((e) => live && setErr(e instanceof Error ? e.message : "Could not load"));
    return () => { live = false; };
  }, [token, tick]);

  return (
    <div className="min-w-0 space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Net worth</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Bring in what you own from your bank, broker and demat statements, add deposits and other savings, and see it all together.</p>
      </header>
      {err && <p role="alert" className="text-sm text-destructive">{err}</p>}

      {nw && (
        <Card>
          <CardContent className="space-y-4 pt-6">
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div><dt className="text-xs text-muted-foreground">Total</dt><dd className="font-num text-2xl font-semibold">{inr(nw.total)}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Stocks</dt><dd className="font-num text-xl font-semibold">{inr(nw.stocks)}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Mutual funds</dt><dd className="font-num text-xl font-semibold">{inr(nw.funds)}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Bank, deposits and other</dt><dd className="font-num text-xl font-semibold">{inr(nw.other)}</dd></div>
            </dl>
            {nw.note && <p role="status" className="rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-sm text-warning">{nw.note}</p>}
            {nw.by_person.length > 1 && (
              <div className="max-w-full overflow-x-auto rounded-lg border border-border">
                <table className="w-full min-w-max text-sm"><thead className="bg-muted/40 text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Person</th><th className="px-3 py-2 text-right">Stocks</th><th className="px-3 py-2 text-right">Funds</th><th className="px-3 py-2 text-right">Other</th><th className="px-3 py-2 text-right">Total</th></tr></thead>
                  <tbody className="font-num">{nw.by_person.map((p) => (<tr key={p.account} className="border-t border-border"><td className="px-3 py-2 font-sans">{p.account}</td><td className="px-3 py-2 text-right">{inr(p.stocks)}</td><td className="px-3 py-2 text-right">{inr(p.funds)}</td><td className="px-3 py-2 text-right">{inr(p.other)}</td><td className="px-3 py-2 text-right font-semibold">{inr(p.total)}</td></tr>))}</tbody></table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {token && <AccountAggregator token={token} onDone={refresh} />}

      {token && (
        <div className="grid min-w-0 gap-6 lg:grid-cols-3">
          <Importer token={token} onDone={refresh} title="Bank statement" path="import-bank" accept=".csv,.xls,.xlsx"
            help="Download the statement from net banking as CSV or Excel (SBI, HDFC, ICICI, Axis, Kotak and most others). Only the latest balance is kept." />
          <Importer token={token} onDone={refresh} title="Broker holdings" path="import-holdings" accept=".csv,.xls,.xlsx"
            help="Zerodha Console > Portfolio > Holdings > Download, or the holdings export from Groww, Upstox, Angel One and others. Stocks with the same symbol are updated." />
          <Importer token={token} onDone={refresh} title="NSDL / CDSL statement" path="import-depository" accept=".pdf,application/pdf" password
            help="The monthly CAS PDF from NSDL or CDSL covers every demat account: stocks, funds, bonds and NPS. It has no purchase cost for stocks, so edit those for correct returns." />
        </div>
      )}

      {token && <AddAsset token={token} onDone={refresh} />}

      {rows && rows.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base text-foreground">Bank, deposits and other assets</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-2">{rows.map((a) => (
              <li key={a.id} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border px-3 py-2 text-sm">
                <span className="font-medium">{a.name}</span>
                <span className="text-xs text-muted-foreground">{KIND_LABEL[a.kind] ?? a.kind}{a.account !== "Me" ? ` · ${a.account}` : ""}{a.rate ? ` · ${a.rate}%` : ""}{a.maturity_date ? ` · matures ${a.maturity_date}` : ""}{a.as_of ? ` · as of ${a.as_of}` : ""}{a.matured ? " · matured" : ""}</span>
                <span className="ml-auto font-num font-semibold">{inr(a.value)}</span>
                <button aria-label={`Remove ${a.name}`} className="text-muted-foreground hover:text-destructive" onClick={async () => { await deleteAsset(token!, a.id); refresh(); }}><Trash2 className="h-3.5 w-3.5" /></button>
              </li>))}</ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Importer({ token, onDone, title, path, accept, help, password }: { token: string; onDone: () => void; title: string; path: "import-bank" | "import-holdings" | "import-depository"; accept: string; help: string; password?: boolean }) {
  const [file, setFile] = React.useState<File | null>(null);
  const [pw, setPw] = React.useState("");
  const [acct, setAcct] = React.useState("Me");
  const [busy, setBusy] = React.useState(false);
  const [note, setNote] = React.useState<Note>(null);
  const id = path;
  const go = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setNote(null);
    try {
      const fields: Record<string, string> = { account: acct.trim() || "Me" };
      if (password) fields.password = pw;
      const r = await uploadAssetFile(token, path, file, fields);
      const msg = (r.message as string) ?? `Imported: ${r.added ?? 0} added, ${r.updated ?? 0} updated.`;
      const skipped = Array.isArray(r.skipped_stocks) && r.skipped_stocks.length ? ` Not matched to an NSE symbol: ${(r.skipped_stocks as string[]).join(", ")}.` : "";
      setNote({ ok: true, text: [msg, r.note, skipped].filter(Boolean).join(" ") }); setPw(""); onDone();
    } catch (e) { setNote({ ok: false, text: e instanceof Error ? e.message : "Import failed" }); }
    finally { setBusy(false); }
  };
  return (
    <Card className="min-w-0">
      <CardHeader><CardTitle className="text-base text-foreground">{title}</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={go} className="space-y-3 text-sm">
          <p className="text-xs text-muted-foreground">{help}</p>
          <input aria-label={`${title} file`} required type="file" accept={accept} onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-2" />
          {password && <div className="space-y-1"><label htmlFor={`${id}-pw`} className="text-xs text-muted-foreground">PDF password (not stored)</label><input id={`${id}-pw`} required type="password" autoComplete="off" value={pw} onChange={(e) => setPw(e.target.value)} className={inputCls} /></div>}
          <div className="space-y-1"><label htmlFor={`${id}-acct`} className="text-xs text-muted-foreground">Whose (family member)</label><input id={`${id}-acct`} maxLength={40} value={acct} onChange={(e) => setAcct(e.target.value)} className={inputCls} /></div>
          <Button type="submit" disabled={busy || !file}>{busy ? "Reading…" : "Import"}</Button>
          {note && <p role="status" className={cn("text-xs", note.ok ? "text-success" : "text-destructive")}>{note.text}</p>}
        </form>
      </CardContent>
    </Card>
  );
}

function AddAsset({ token, onDone }: { token: string; onDone: () => void }) {
  const [kind, setKind] = React.useState("fd");
  const [name, setName] = React.useState("");
  const [amount, setAmount] = React.useState("");
  const [rate, setRate] = React.useState("");
  const [start, setStart] = React.useState("");
  const [mat, setMat] = React.useState("");
  const [acct, setAcct] = React.useState("Me");
  const [note, setNote] = React.useState<Note>(null);
  const deposit = kind === "fd" || kind === "rd";
  const go = async (e: React.FormEvent) => {
    e.preventDefault(); setNote(null);
    try {
      await addAsset(token, { kind, name: name.trim(), amount: Number(amount), rate: rate ? Number(rate) : null, start_date: start || null, maturity_date: mat || null, account: acct.trim() || "Me" });
      setNote({ ok: true, text: `Added ${name}.` }); setName(""); setAmount(""); setRate(""); setStart(""); setMat(""); onDone();
    } catch (e) { setNote({ ok: false, text: e instanceof Error ? e.message : "Not added" }); }
  };
  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Add a deposit or other asset</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={go} className="grid min-w-0 gap-3 sm:grid-cols-4 lg:grid-cols-8 lg:items-end">
          <div className="space-y-1 lg:col-span-1"><label htmlFor="as-k" className="text-xs text-muted-foreground">Type</label>
            <select id="as-k" value={kind} onChange={(e) => setKind(e.target.value)} className={inputCls}>{Object.entries(KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
          <div className="space-y-1 lg:col-span-2"><label htmlFor="as-n" className="text-xs text-muted-foreground">Name</label><input id="as-n" required maxLength={100} placeholder="SBI FD 2027" value={name} onChange={(e) => setName(e.target.value)} className={inputCls} /></div>
          <div className="space-y-1"><label htmlFor="as-a" className="text-xs text-muted-foreground">{deposit ? "Amount deposited (₹)" : "Current value (₹)"}</label><input id="as-a" required type="number" step="any" min={1} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className={inputCls} /></div>
          <div className="space-y-1"><label htmlFor="as-r" className="text-xs text-muted-foreground">Rate % a year</label><input id="as-r" required={deposit} type="number" step="any" min={0} max={50} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} className={inputCls} /></div>
          <div className="space-y-1"><label htmlFor="as-s" className="text-xs text-muted-foreground">Start date</label><input id="as-s" required={deposit} type="date" value={start} onChange={(e) => setStart(e.target.value)} className={inputCls} /></div>
          <div className="space-y-1"><label htmlFor="as-m" className="text-xs text-muted-foreground">Maturity</label><input id="as-m" type="date" value={mat} onChange={(e) => setMat(e.target.value)} className={inputCls} /></div>
          <div className="space-y-1"><label htmlFor="as-w" className="text-xs text-muted-foreground">Whose</label><input id="as-w" maxLength={40} value={acct} onChange={(e) => setAcct(e.target.value)} className={inputCls} /></div>
          <div className="sm:col-span-4 lg:col-span-8"><Button type="submit">Add</Button>{note && <span role="status" className={cn("ml-3 text-xs", note.ok ? "text-success" : "text-destructive")}>{note.text}</span>}</div>
        </form>
        {deposit && <p className="mt-2 text-xs text-muted-foreground">Fixed deposits are valued with quarterly compounding, as Indian banks do, up to maturity.</p>}
      </CardContent>
    </Card>
  );
}
