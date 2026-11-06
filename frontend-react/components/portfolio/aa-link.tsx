"use client";

import * as React from "react";
import { getAAStatus, startAAConsent, syncAA } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const inputCls = "h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30";

/** Link every bank account, deposit, fund and demat account by consent, through an RBI-licensed Account Aggregator. */
export function AccountAggregator({ token, onDone }: { token: string; onDone: () => void }) {
  const [st, setSt] = React.useState<Awaited<ReturnType<typeof getAAStatus>> | null>(null);
  const [mobile, setMobile] = React.useState("");
  const [acct, setAcct] = React.useState("Me");
  const [busy, setBusy] = React.useState<string | null>(null);
  const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    getAAStatus(token).then((r) => live && setSt(r)).catch(() => {});
    return () => { live = false; };
  }, [token, tick]);
  const start = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy("start"); setNote(null);
    try { const r = await startAAConsent(token, mobile.trim(), acct.trim() || "Me", `${window.location.origin}/networth?aa=back`); window.location.href = r.url; }
    catch (err) { setNote({ ok: false, text: err instanceof Error ? err.message : "Could not start" }); setBusy(null); }
  };
  const sync = async (id: string) => {
    setBusy(id); setNote(null);
    try {
      const r = await syncAA(token, id);
      const extra = [r.unmatched_stocks.length ? `Not matched to an NSE symbol: ${r.unmatched_stocks.join(", ")}.` : "", r.failed_accounts.length ? `No data from: ${r.failed_accounts.join(", ")}.` : ""].filter(Boolean).join(" ");
      setNote({ ok: true, text: `${r.message} ${extra}` }); onDone();
    } catch (err) { setNote({ ok: false, text: err instanceof Error ? err.message : "Sync failed" }); }
    finally { setBusy(null); setTick((t) => t + 1); }
  };
  if (!st) return null;
  return (
    <Card>
      <CardHeader><CardTitle className="text-base text-foreground">Link all your accounts (Account Aggregator)</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">The RBI&apos;s Account Aggregator system, the same route bank apps such as IDFC FIRST use to show all your accounts in one place. You approve once on the aggregator&apos;s page; your banks, depositories and fund houses then send balances, deposits, funds and stocks directly. You can revoke the consent any time in your aggregator app.</p>
        {!st.configured ? (
          <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">Not switched on for this server yet: it needs an Account Aggregator (FIU) product from Setu. Until then, use the statement imports below.</p>
        ) : (
          <form onSubmit={start} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <div className="space-y-1"><label htmlFor="aa-m" className="text-xs text-muted-foreground">Mobile linked to your bank accounts</label>
              <input id="aa-m" required inputMode="numeric" pattern="[6-9][0-9]{9}" maxLength={10} placeholder="9876543210" value={mobile} onChange={(e) => setMobile(e.target.value)} className={inputCls} /></div>
            <div className="space-y-1"><label htmlFor="aa-a" className="text-xs text-muted-foreground">Whose accounts</label><input id="aa-a" maxLength={40} value={acct} onChange={(e) => setAcct(e.target.value)} className={inputCls} /></div>
            <Button type="submit" disabled={!!busy}>{busy === "start" ? "Opening…" : "Link accounts"}</Button>
          </form>
        )}
        {st.consents.length > 0 && (
          <ul className="space-y-1">{st.consents.map((c) => (
            <li key={c.consent_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2">
              <span>{c.account}</span><span className="text-xs text-muted-foreground">consent {c.status.toLowerCase()}{c.last_synced ? `, synced ${new Date(c.last_synced).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}` : ""}</span>
              <Button size="sm" variant="outline" className="ml-auto" disabled={!!busy || !st.configured} onClick={() => sync(c.consent_id)}>{busy === c.consent_id ? "Syncing…" : "Sync now"}</Button>
            </li>))}</ul>
        )}
        {note && <p role="status" className={cn("text-xs", note.ok ? "text-success" : "text-destructive")}>{note.text}</p>}
      </CardContent>
    </Card>
  );
}
