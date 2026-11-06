"use client";

import * as React from "react";
import { BellRing, RotateCcw, Trash2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import {
  addAlert, checkAlerts, getAlertSettings, getAlerts, rearmAlert, removeAlert, saveTelegramChat, testTelegram,
  type AlertCheck, type AlertRow, type AlertSettings, type AlertType,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const inputCls = "font-num h-10 w-full min-w-0 rounded-lg border border-border bg-card px-3 text-sm outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30";

const KINDS: { value: AlertType; label: string; unit: string; def: string; help: string }[] = [
  { value: "price_above", label: "Price at or above", unit: "₹", def: "", help: "Fires when the latest close is at or above this price." },
  { value: "price_below", label: "Price at or below", unit: "₹", def: "", help: "Fires when the latest close is at or below this price." },
  { value: "vol_spike", label: "Unusually wide day", unit: "×", def: "2", help: "Fires when a day's high-to-low range is this many times the stock's normal range (average of the 60 days before)." },
];

function describe(a: AlertRow) {
  const v = a.price_target ?? 0;
  if (a.alert_type === "price_above") return `Close at or above ₹${v.toLocaleString("en-IN")}`;
  if (a.alert_type === "price_below") return `Close at or below ₹${v.toLocaleString("en-IN")}`;
  if (a.alert_type === "vol_spike") return `Day's range ${v}× its normal size`;
  return a.alert_type;
}

export default function AlertsPage() {
  const { token } = useAuth();
  const [rows, setRows] = React.useState<AlertRow[] | null>(null);
  const [settings, setSettings] = React.useState<AlertSettings | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [kind, setKind] = React.useState<AlertType>("price_above");
  const [ticker, setTicker] = React.useState("");
  const [level, setLevel] = React.useState("");
  const [adding, setAdding] = React.useState(false);
  const [checking, setChecking] = React.useState(false);
  const [result, setResult] = React.useState<AlertCheck | null>(null);
  const [chat, setChat] = React.useState("");
  const [tgMsg, setTgMsg] = React.useState<{ ok: boolean; text: string } | null>(null);
  const [tgBusy, setTgBusy] = React.useState(false);

  const [tick, setTick] = React.useState(0);
  const load = React.useCallback(() => setTick((t) => t + 1), []);

  React.useEffect(() => {
    if (!token) return;
    let live = true;
    Promise.all([getAlerts(token), getAlertSettings(token)])
      .then(([a, s]) => {
        if (!live) return;
        setRows(a.alerts);
        setSettings(s);
        setChat((c) => c || s.telegram_chat_id || "");
        setError(null);
      })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "Could not load alerts"); });
    return () => { live = false; };
  }, [token, tick]);

  const spec = KINDS.find((k) => k.value === kind)!;

  const onAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setAdding(true); setError(null);
    try {
      await addAlert(token, { ticker: ticker.trim().toUpperCase(), alert_type: kind, price_target: Number(level) });
      setTicker(""); setLevel(kind === "vol_spike" ? spec.def : "");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the alert");
    } finally { setAdding(false); }
  };

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try { await fn(); load(); } catch (err) { setError(err instanceof Error ? err.message : "That did not work"); }
  };

  const onCheck = async () => {
    if (!token) return;
    setChecking(true); setError(null);
    try { setResult(await checkAlerts(token)); load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not check alerts"); }
    finally { setChecking(false); }
  };

  const onSaveChat = async () => {
    if (!token) return;
    setTgBusy(true); setTgMsg(null);
    try { await saveTelegramChat(token, chat.trim()); setTgMsg({ ok: true, text: chat.trim() ? "Saved." : "Removed." }); load(); }
    catch (err) { setTgMsg({ ok: false, text: err instanceof Error ? err.message : "Not saved" }); }
    finally { setTgBusy(false); }
  };

  const onTest = async () => {
    if (!token) return;
    setTgBusy(true); setTgMsg(null);
    try { const r = await testTelegram(token); setTgMsg({ ok: true, text: r.message }); }
    catch (err) { setTgMsg({ ok: false, text: err instanceof Error ? err.message : "Test failed" }); }
    finally { setTgBusy(false); }
  };

  return (
    <div className="min-w-0 space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Alerts</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Get told when a stock closes past a price you chose, or has an unusually wide day. Alerts read the latest end-of-day close, not live prices, and are checked every {settings?.check_every_minutes ?? 30} minutes.
        </p>
      </header>

      {settings && !settings.real_data && (
        <div role="status" className="rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-sm text-warning">
          This server is using placeholder prices. Alerts still run so you can see how they work, but they are marked as placeholder and never sent to Telegram.
        </div>
      )}
      {error && <div role="alert" className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-base text-foreground">New alert</CardTitle></CardHeader>
            <CardContent>
              <form onSubmit={onAdd} className="grid min-w-0 gap-3 sm:grid-cols-[1.2fr_1fr_1fr_auto] sm:items-end">
                <div className="min-w-0 space-y-1">
                  <label htmlFor="al-kind" className="text-xs text-muted-foreground">When</label>
                  <select id="al-kind" value={kind} onChange={(e) => { const k = e.target.value as AlertType; setKind(k); setLevel(KINDS.find((x) => x.value === k)!.def); }} className={inputCls}>
                    {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                  </select>
                </div>
                <div className="min-w-0 space-y-1">
                  <label htmlFor="al-ticker" className="text-xs text-muted-foreground">Stock symbol</label>
                  <input id="al-ticker" required maxLength={20} pattern="[A-Za-z0-9._&\-]+" autoCapitalize="characters" autoCorrect="off" spellCheck={false} placeholder="TCS" value={ticker} onChange={(e) => setTicker(e.target.value)} className={inputCls} />
                </div>
                <div className="min-w-0 space-y-1">
                  <label htmlFor="al-level" className="text-xs text-muted-foreground">{kind === "vol_spike" ? "Times normal (1.2 to 10)" : "Price (₹)"}</label>
                  <input id="al-level" required type="number" inputMode="decimal" step="any" min={kind === "vol_spike" ? 1.2 : 0.01} max={kind === "vol_spike" ? 10 : undefined} value={level} onChange={(e) => setLevel(e.target.value)} className={inputCls} />
                </div>
                <Button type="submit" disabled={adding} className="h-10">{adding ? "Adding…" : "Add alert"}</Button>
              </form>
              <p className="mt-2 text-xs text-muted-foreground">{spec.help}</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between gap-3">
              <CardTitle className="text-base text-foreground">Your alerts</CardTitle>
              <Button variant="outline" size="sm" onClick={onCheck} disabled={checking || !rows?.length} className="shrink-0">
                <BellRing className="mr-1.5 h-4 w-4" aria-hidden />{checking ? "Checking…" : "Check now"}
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {result && (
                <div role="status" className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
                  Checked {result.checked}: {result.fired.length} fired{result.skipped.length ? `, ${result.skipped.length} skipped` : ""}.
                  {result.skipped.map((s, i) => <div key={i} className="text-xs text-muted-foreground">{s.ticker}: {s.reason}</div>)}
                </div>
              )}
              {rows === null && !error && <p className="text-sm text-muted-foreground">Loading…</p>}
              {rows?.length === 0 && <p className="text-sm text-muted-foreground">No alerts yet. Add one above, for example TCS closing at or above a price you are watching.</p>}
              <ul className="space-y-2">
                {rows?.map((a) => (
                  <li key={a.id} className="min-w-0 rounded-lg border border-border bg-card/60 p-3">
                    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="font-num font-semibold">{a.ticker}</span>
                      <span className="min-w-0 text-sm text-muted-foreground">{describe(a)}</span>
                      <span className={cn("ml-auto rounded-md border px-2 py-0.5 text-xs", a.is_active ? "border-success/40 text-success" : "border-border text-muted-foreground")}>
                        {a.is_active ? "Watching" : "Fired, off"}
                      </span>
                    </div>
                    {a.last_message && <p className="mt-2 break-words text-xs text-muted-foreground">Last: {a.last_message}</p>}
                    <div className="mt-2 flex items-center gap-2">
                      {!a.is_active && (
                        <Button variant="outline" size="sm" onClick={() => act(() => rearmAlert(token!, a.id))}>
                          <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />Turn on again
                        </Button>
                      )}
                      <Button variant="ghost" size="sm" aria-label={`Remove ${a.ticker} alert`} onClick={() => act(() => removeAlert(token!, a.id))}>
                        <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden />Remove
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>

        <Card className="h-fit min-w-0">
          <CardHeader><CardTitle className="text-base text-foreground">Send to Telegram</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            {settings && !settings.telegram_available ? (
              <p className="text-muted-foreground">This server has no Telegram bot set up, so alerts show only on this page. The person running the server adds a bot token to turn this on.</p>
            ) : (
              <>
                <p className="text-muted-foreground">Message the server&apos;s bot once in Telegram, then paste your chat id here. Get your id by messaging @userinfobot.</p>
                <div className="space-y-1">
                  <label htmlFor="tg-chat" className="text-xs text-muted-foreground">Your Telegram chat id</label>
                  <input id="tg-chat" inputMode="numeric" autoComplete="off" placeholder="123456789" value={chat} onChange={(e) => setChat(e.target.value)} className={inputCls} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={onSaveChat} disabled={tgBusy}>Save</Button>
                  <Button size="sm" variant="outline" onClick={onTest} disabled={tgBusy || !settings?.telegram_chat_id}>Send test message</Button>
                </div>
                {tgMsg && <p role="status" className={cn("text-xs", tgMsg.ok ? "text-success" : "text-destructive")}>{tgMsg.text}</p>}
              </>
            )}
            <p className="border-t border-border pt-3 text-xs text-muted-foreground">Alerts are information, not advice. A price level you picked being reached is not a reason to trade by itself.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
