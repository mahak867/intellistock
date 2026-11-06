"use client";

import * as React from "react";
import { useAuth } from "@/lib/auth-context";
import { getMarketStatus, sendFeedback } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const inputCls = "h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30";

const FAQ: { q: string; a: string }[] = [
  { q: "Are the prices live?", a: "No. IntelliStock works on end-of-day prices, so a number is the last close, never a tick. For live prices and orders, use your broker's app." },
  { q: "Does it tell me what to buy or sell?", a: "No. The forecast shows a likely price range and how well that range has held in testing. We tested the direction model on 48 NSE large caps from 2016 to 2026: it did not beat simply guessing \"up\", and 0 of 48 stocks passed the significance test. So the app does not show Buy or Sell." },
  { q: "What is reliable, then?", a: "Volatility. On the same test the volatility forecast beat the naive baseline for 44 of 48 stocks at 5 days, and the 80% price range held about 85% of the time on newer data at 10 days (between 72% and 92% depending on the stock)." },
  { q: "Why does a page say placeholder prices?", a: "Until the server owner loads licensed NSE end-of-day files, prices are generated, not real. Every screen that uses them says so, and portfolio profit and loss is left blank rather than computed from them." },
  { q: "Where do fundamentals come from?", a: "From you. The fundamentals screener reads a CSV you export (for example from Screener.in) and filters on exactly those numbers." },
  { q: "Can I trade from here or connect my broker?", a: "Not yet. IntelliStock does not place orders or link to brokers. Your portfolio is entered by hand or imported from a CSV." },
  { q: "Is this investment advice?", a: "No. IntelliStock is not a SEBI-registered investment adviser or research analyst. Use it to check risk and costs, and talk to a registered adviser before acting on anything." },
];

export default function HelpPage() {
  const { token } = useAuth();
  const [status, setStatus] = React.useState<Awaited<ReturnType<typeof getMarketStatus>> | null>(null);
  const [category, setCategory] = React.useState<"bug" | "data" | "feature" | "other">("bug");
  const [message, setMessage] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);

  React.useEffect(() => {
    if (!token) return;
    getMarketStatus(token).then(setStatus).catch(() => setStatus(null));
  }, [token]);

  const onSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setBusy(true); setNote(null);
    try {
      await sendFeedback(token, { category, message: message.trim(), page: "/help" });
      setMessage(""); setNote({ ok: true, text: "Sent. Thank you." });
    } catch (err) {
      setNote({ ok: false, text: err instanceof Error ? err.message : "Could not send" });
    } finally { setBusy(false); }
  };

  return (
    <div className="min-w-0 space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Help</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">What this app can and cannot tell you, and a way to report a problem.</p>
      </header>

      <Card>
        <CardHeader><CardTitle className="text-base text-foreground">Data on this server</CardTitle></CardHeader>
        <CardContent className="text-sm">
          {!status ? <p className="text-muted-foreground">Could not read the data status.</p> : status.real_data ? (
            <p>Real end-of-day prices{status.last ? `, latest ${status.last}` : ""}{status.symbols ? `, ${status.symbols} stocks` : ""}. {status.licensed_to_serve ? "" : "Not licensed to show to users yet."}</p>
          ) : (
            <p className="text-warning">Placeholder prices. {status.note}</p>
          )}
        </CardContent>
      </Card>

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section aria-labelledby="faq-h" className="min-w-0 space-y-2">
          <h2 id="faq-h" className="font-display text-xl font-semibold">Questions</h2>
          {FAQ.map((f) => (
            <details key={f.q} className="group rounded-lg border border-border bg-card/60 px-4 py-3">
              <summary className="cursor-pointer list-none text-sm font-medium focus-visible:outline-2 outline-primary [&::-webkit-details-marker]:hidden">{f.q}</summary>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{f.a}</p>
            </details>
          ))}
        </section>

        <Card className="h-fit min-w-0">
          <CardHeader><CardTitle className="text-base text-foreground">Report a problem or ask for a feature</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={onSend} className="space-y-3">
              <div className="space-y-1">
                <label htmlFor="fb-cat" className="text-xs text-muted-foreground">What is it about?</label>
                <select id="fb-cat" value={category} onChange={(e) => setCategory(e.target.value as typeof category)} className={inputCls}>
                  <option value="bug">Something is broken</option>
                  <option value="data">A number looks wrong</option>
                  <option value="feature">I want a feature</option>
                  <option value="other">Something else</option>
                </select>
              </div>
              <div className="space-y-1">
                <label htmlFor="fb-msg" className="text-xs text-muted-foreground">Tell us what happened</label>
                <textarea id="fb-msg" required minLength={5} maxLength={2000} rows={5} value={message} onChange={(e) => setMessage(e.target.value)} className={cn(inputCls, "h-auto py-2 leading-relaxed")} />
                <p className="text-xs text-muted-foreground">Include the stock and the page if you can. Do not include passwords.</p>
              </div>
              <div className="flex items-center gap-3">
                <Button type="submit" disabled={busy || message.trim().length < 5}>{busy ? "Sending…" : "Send"}</Button>
                {note && <span role="status" className={cn("text-xs", note.ok ? "text-success" : "text-destructive")}>{note.text}</span>}
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
