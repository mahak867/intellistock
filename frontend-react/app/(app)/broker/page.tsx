"use client";

import * as React from "react";
import { useAuth } from "@/lib/auth-context";
import {
  disconnectBroker, getBrokerHoldings, getBrokerStatus, getOrderLog, importBrokerHoldings, placeOrder, previewOrder, saveBrokerKeys,
  type BrokerHolding, type BrokerStatus, type OrderLogRow, type OrderPreview, type OrderTicket,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const inputCls = "font-num h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30";
const inr = (n: number | null | undefined) => (n == null ? "—" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
const errText = (e: unknown, f: string) => (e instanceof Error ? e.message : f);

function Note({ ok, text }: { ok: boolean; text: string }) {
  return <p role="status" className={cn("text-sm", ok ? "text-success" : "text-destructive")}>{text}</p>;
}

function Connect({ token, status, onChange }: { token: string; status: BrokerStatus; onChange: () => void }) {
  const [key, setKey] = React.useState("");
  const [secret, setSecret] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [origin, setOrigin] = React.useState("");
  React.useEffect(() => { Promise.resolve().then(() => setOrigin(window.location.origin)); }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setNote(null);
    try { const r = await saveBrokerKeys(token, key.trim(), secret.trim()); setSecret(""); setNote({ ok: true, text: r.message }); onChange(); }
    catch (err) { setNote({ ok: false, text: errText(err, "Not saved") }); }
    finally { setBusy(false); }
  };
  const disconnect = async () => {
    setBusy(true);
    try { await disconnectBroker(token); setNote({ ok: true, text: "Disconnected. Your keys and session were deleted." }); onChange(); }
    catch (err) { setNote({ ok: false, text: errText(err, "Could not disconnect") }); }
    finally { setBusy(false); }
  };

  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Zerodha (Kite Connect)</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        {status.session_valid ? (
          <div className="space-y-2">
            <p>Connected as <span className="font-num font-semibold">{status.broker_user_id}</span>{status.broker_user_name ? ` (${status.broker_user_name})` : ""}.</p>
            <p className="text-muted-foreground">Zerodha ends every session at 6:00 AM, so you log in again each trading day{status.session_expires_at ? ` (this one ends ${new Date(status.session_expires_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" })} IST)` : ""}.</p>
          </div>
        ) : status.connected ? (
          <div className="space-y-2">
            <p>Your keys are saved ({status.api_key}). Log in with Zerodha to start a session.</p>
            <a href={status.login_url} className="inline-flex h-10 items-center rounded-lg bg-primary px-4 font-medium text-primary-foreground active:scale-[0.97]">Log in with Zerodha</a>
          </div>
        ) : (
          <ol className="list-decimal space-y-1.5 pl-5 text-muted-foreground">
            <li>Create an app at developers.kite.trade (your own Zerodha developer account).</li>
            <li>Set its Redirect URL to <span className="font-num break-all text-foreground">{origin || "this site"}/broker/callback</span>.</li>
            <li>To place orders, add this server&apos;s static IP to your Kite developer profile. Zerodha rejects orders from other IPs.</li>
            <li>Paste the app&apos;s API key and secret below, then log in with Zerodha.</li>
          </ol>
        )}
        {!status.session_valid && (
          <form onSubmit={save} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <div className="min-w-0 space-y-1">
              <label htmlFor="bk-key" className="text-xs text-muted-foreground">API key</label>
              <input id="bk-key" required autoComplete="off" autoCapitalize="none" spellCheck={false} value={key} onChange={(e) => setKey(e.target.value)} className={inputCls} />
            </div>
            <div className="min-w-0 space-y-1">
              <label htmlFor="bk-secret" className="text-xs text-muted-foreground">API secret</label>
              <input id="bk-secret" required type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} className={inputCls} />
            </div>
            <Button type="submit" disabled={busy} className="h-10">{status.connected ? "Replace keys" : "Save keys"}</Button>
          </form>
        )}
        <p className="text-xs text-muted-foreground">Your secret and session are stored encrypted and never shown again. IntelliStock is not a broker and is not SEBI-registered; orders go to Zerodha only when you confirm each one.</p>
        {status.connected && <Button variant="outline" size="sm" onClick={disconnect} disabled={busy}>Disconnect and delete keys</Button>}
        {note && <Note {...note} />}
      </CardContent>
    </Card>
  );
}

function Holdings({ token }: { token: string }) {
  const [rows, setRows] = React.useState<BrokerHolding[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [armReplace, setArmReplace] = React.useState(false);
  const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);
  React.useEffect(() => {
    let live = true;
    getBrokerHoldings(token).then((r) => live && setRows(r.holdings)).catch((e) => live && setErr(errText(e, "Could not load holdings")));
    return () => { live = false; };
  }, [token]);
  const doImport = async (mode: "merge" | "replace") => {
    setBusy(true); setNote(null); setArmReplace(false);
    try {
      const r = await importBrokerHoldings(token, mode);
      setNote({ ok: true, text: `Portfolio updated: ${r.added} added, ${r.updated} updated${r.removed ? `, ${r.removed} removed` : ""}. Zerodha does not give buy dates, so imported holdings are dated today.` });
    } catch (e) { setNote({ ok: false, text: errText(e, "Import failed") }); }
    finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Holdings at Zerodha</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {err && <Note ok={false} text={err} />}
        {!rows && !err && <p className="text-sm text-muted-foreground">Loading…</p>}
        {rows && rows.length === 0 && <p className="text-sm text-muted-foreground">No holdings in this Zerodha account.</p>}
        {rows && rows.length > 0 && (
          <div className="max-w-full overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-max text-sm">
              <thead className="bg-muted/40 text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Stock</th><th className="px-3 py-2 text-right">Qty</th><th className="px-3 py-2 text-right">Avg price</th><th className="px-3 py-2 text-right">Last price</th><th className="px-3 py-2 text-right">P&amp;L</th></tr></thead>
              <tbody className="font-num">
                {rows.map((h) => (
                  <tr key={h.ticker} className="border-t border-border">
                    <td className="px-3 py-2 font-sans font-medium">{h.ticker}</td><td className="px-3 py-2 text-right">{h.quantity}</td>
                    <td className="px-3 py-2 text-right">{inr(h.avg_buy_price)}</td><td className="px-3 py-2 text-right">{inr(h.last_price)}</td>
                    <td className={cn("px-3 py-2 text-right", (h.pnl ?? 0) >= 0 ? "text-success" : "text-destructive")}>{inr(h.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rows && rows.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => doImport("merge")} disabled={busy}>Add to my portfolio</Button>
            {!armReplace
              ? <Button size="sm" variant="outline" onClick={() => setArmReplace(true)} disabled={busy}>Replace my portfolio…</Button>
              : <Button size="sm" variant="destructive" onClick={() => doImport("replace")} disabled={busy}>Yes, delete my portfolio and use these</Button>}
          </div>
        )}
        {note && <Note {...note} />}
      </CardContent>
    </Card>
  );
}

const EMPTY: OrderTicket = { tradingsymbol: "", exchange: "NSE", side: "BUY", quantity: 1, price: 0, product: "CNC" };

function Ticket({ token, onSent }: { token: string; onSent: () => void }) {
  const [o, setO] = React.useState<OrderTicket>(EMPTY);
  const [qty, setQty] = React.useState("1");
  const [price, setPrice] = React.useState("");
  const [pv, setPv] = React.useState<OrderPreview | null>(null);
  const [left, setLeft] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);

  React.useEffect(() => {
    if (!pv) return;
    const end = Date.now() + pv.expires_in_seconds * 1000;
    const t = setInterval(() => { const s = Math.max(0, Math.round((end - Date.now()) / 1000)); setLeft(s); if (!s) clearInterval(t); }, 250);
    return () => clearInterval(t);
  }, [pv]);

  const ticket = (): OrderTicket => ({ ...o, tradingsymbol: o.tradingsymbol.trim().toUpperCase(), quantity: Number(qty), price: Number(price) });
  const doPreview = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setNote(null); setPv(null);
    try { const r = await previewOrder(token, ticket()); setLeft(r.expires_in_seconds); setPv(r); } catch (err) { setNote({ ok: false, text: errText(err, "Could not check the order") }); }
    finally { setBusy(false); }
  };
  const send = async () => {
    if (!pv) return;
    setBusy(true); setNote(null);
    try { const r = await placeOrder(token, pv.order, pv.confirm_token); setNote({ ok: true, text: `${r.message} Zerodha order id ${r.broker_order_id}.` }); setPv(null); onSent(); }
    catch (err) { setNote({ ok: false, text: errText(err, "Not sent") }); setPv(null); onSent(); }
    finally { setBusy(false); }
  };

  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Place a limit order</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={doPreview} className="grid min-w-0 gap-3 sm:grid-cols-3">
          <div className="min-w-0 space-y-1">
            <label htmlFor="o-sym" className="text-xs text-muted-foreground">Stock symbol</label>
            <input id="o-sym" required maxLength={30} autoCapitalize="characters" autoCorrect="off" spellCheck={false} placeholder="TCS" value={o.tradingsymbol} onChange={(e) => { setO({ ...o, tradingsymbol: e.target.value }); setPv(null); }} className={inputCls} />
          </div>
          <div className="min-w-0 space-y-1">
            <label htmlFor="o-side" className="text-xs text-muted-foreground">Buy or sell</label>
            <select id="o-side" value={o.side} onChange={(e) => { setO({ ...o, side: e.target.value as OrderTicket["side"] }); setPv(null); }} className={inputCls}><option value="BUY">Buy</option><option value="SELL">Sell</option></select>
          </div>
          <div className="min-w-0 space-y-1">
            <label htmlFor="o-prod" className="text-xs text-muted-foreground">Product</label>
            <select id="o-prod" value={o.product} onChange={(e) => { setO({ ...o, product: e.target.value as OrderTicket["product"] }); setPv(null); }} className={inputCls}><option value="CNC">Delivery (CNC)</option><option value="MIS">Intraday (MIS)</option></select>
          </div>
          <div className="min-w-0 space-y-1">
            <label htmlFor="o-qty" className="text-xs text-muted-foreground">Quantity</label>
            <input id="o-qty" required type="number" inputMode="numeric" min={1} step={1} value={qty} onChange={(e) => { setQty(e.target.value); setPv(null); }} className={inputCls} />
          </div>
          <div className="min-w-0 space-y-1">
            <label htmlFor="o-price" className="text-xs text-muted-foreground">Limit price (₹)</label>
            <input id="o-price" required type="number" inputMode="decimal" min={0.05} step={0.05} value={price} onChange={(e) => { setPrice(e.target.value); setPv(null); }} className={inputCls} />
          </div>
          <div className="min-w-0 space-y-1">
            <label htmlFor="o-exch" className="text-xs text-muted-foreground">Exchange</label>
            <select id="o-exch" value={o.exchange} onChange={(e) => { setO({ ...o, exchange: e.target.value as OrderTicket["exchange"] }); setPv(null); }} className={inputCls}><option>NSE</option><option>BSE</option></select>
          </div>
          <div className="sm:col-span-3"><Button type="submit" disabled={busy} variant="outline">Check order</Button></div>
        </form>

        {pv && (
          <div className="space-y-3 rounded-xl border border-primary/40 bg-primary/5 p-4 text-sm">
            <p className="text-base">
              <span className={pv.order.side === "BUY" ? "text-success" : "text-destructive"}>{pv.order.side === "BUY" ? "Buy" : "Sell"}</span>{" "}
              <span className="font-num">{pv.order.quantity}</span> {pv.order.tradingsymbol} on {pv.order.exchange} at <span className="font-num">{inr(pv.order.price)}</span> limit, {pv.order.product === "CNC" ? "delivery" : "intraday"}, good for today.
            </p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
              <dt className="text-muted-foreground">Order value</dt><dd className="font-num">{inr(pv.value)}</dd>
              <dt className="text-muted-foreground">Charges (estimate)</dt><dd className="font-num">{inr(pv.charges_estimate)}</dd>
              <dt className="text-muted-foreground">Last price</dt><dd className="font-num">{inr(pv.last_price)}</dd>
              <dt className="text-muted-foreground">Your price vs last</dt><dd className="font-num">{pv.gap_from_last_pct == null ? "—" : `${pv.gap_from_last_pct > 0 ? "+" : ""}${pv.gap_from_last_pct}%`}</dd>
            </dl>
            <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">{pv.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={send} disabled={busy || left === 0} variant={pv.order.side === "BUY" ? "default" : "destructive"}>
                {busy ? "Sending…" : `Send ${pv.order.side === "BUY" ? "buy" : "sell"} order to Zerodha`}
              </Button>
              <Button variant="ghost" onClick={() => setPv(null)} disabled={busy}>Cancel</Button>
              <span className="text-xs text-muted-foreground">{left > 0 ? `Confirm within ${left}s` : "Expired. Check the order again."}</span>
            </div>
          </div>
        )}
        {note && <Note {...note} />}
      </CardContent>
    </Card>
  );
}

function OrderLog({ token, tick }: { token: string; tick: number }) {
  const [rows, setRows] = React.useState<OrderLogRow[] | null>(null);
  React.useEffect(() => {
    let live = true;
    getOrderLog(token).then((r) => live && setRows(r.orders)).catch(() => live && setRows([]));
    return () => { live = false; };
  }, [token, tick]);
  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Orders sent from IntelliStock</CardTitle></CardHeader>
      <CardContent>
        {!rows?.length ? <p className="text-sm text-muted-foreground">None yet. Every order you send is recorded here, including rejected ones.</p> : (
          <ul className="space-y-2">
            {rows.map((r) => (
              <li key={r.id} className="rounded-lg border border-border bg-card/60 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className={r.side === "BUY" ? "text-success" : "text-destructive"}>{r.side}</span>
                  <span className="font-num">{r.quantity} {r.symbol} @ {inr(r.price)}</span>
                  <span className={cn("ml-auto rounded-md border px-2 py-0.5 text-xs", r.status === "sent" ? "border-success/40 text-success" : "border-destructive/40 text-destructive")}>{r.status}</span>
                </div>
                <p className="mt-1 break-words text-xs text-muted-foreground">{r.time ? new Date(r.time).toLocaleString("en-IN") : ""}{r.broker_order_id ? ` · Zerodha id ${r.broker_order_id}` : ""}{r.message ? ` · ${r.message}` : ""}</p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function BrokerPage() {
  const { token } = useAuth();
  const [status, setStatus] = React.useState<BrokerStatus | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [tick, setTick] = React.useState(0);
  const refresh = React.useCallback(() => setTick((t) => t + 1), []);
  React.useEffect(() => {
    if (!token) return;
    let live = true;
    getBrokerStatus(token).then((s) => { if (live) { setStatus(s); setErr(null); } }).catch((e) => live && setErr(errText(e, "Could not load")));
    return () => { live = false; };
  }, [token, tick]);

  return (
    <div className="min-w-0 space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Broker</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Connect your own Zerodha account to see live holdings and prices, copy holdings into your portfolio, and send limit orders you confirm one at a time.</p>
      </header>
      {err && <Note ok={false} text={err} />}
      {status && token && (
        <div className="grid min-w-0 gap-6 xl:grid-cols-2">
          <div className="min-w-0 space-y-6">
            <Connect token={token} status={status} onChange={refresh} />
            {status.session_valid && <Holdings key={`h${tick}`} token={token} />}
          </div>
          {status.session_valid && (
            <div className="min-w-0 space-y-6">
              {status.orders_enabled ? <Ticket token={token} onSent={refresh} /> : <Card><CardContent className="pt-6 text-sm text-muted-foreground">Order placement is turned off on this server.</CardContent></Card>}
              <OrderLog token={token} tick={tick} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
