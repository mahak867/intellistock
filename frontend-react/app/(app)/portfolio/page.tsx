"use client";

import * as React from "react";
import { Plus, Trash2, TrendingUp, TrendingDown } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import {
  getPortfolio,
  addPortfolioEntry,
  removePortfolioEntry,
  getSignal,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

interface Holding {
  id: string;
  ticker: string;
  quantity: number;
  avg_buy_price: number;
  invested_value: number;
  buy_date: string;
  current_price?: number;
  loadError?: boolean;
}

export default function PortfolioPage() {
  const { token } = useAuth();
  const [holdings, setHoldings] = React.useState<Holding[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [pricesLoading, setPricesLoading] = React.useState(false);
  const [placeholderPrices, setPlaceholderPrices] = React.useState(false);
  const [showForm, setShowForm] = React.useState(false);
  const [form, setForm] = React.useState({
    ticker: "",
    quantity: "",
    avg_buy_price: "",
    buy_date: new Date().toISOString().slice(0, 10),
  });
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await getPortfolio(token);
      const base: Holding[] = res.portfolio;
      setHoldings(base);
      setLoading(false);

      // Current prices from the market API in one call (real NSE end-of-day data when configured), falling back to the
      // older per-stock signal call. A holding with no price is marked, not guessed.
      setPricesLoading(true);
      const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api/v1";
      let quotes: Record<string, number> = {};
      let placeholder = false;
      try {
        const names = Array.from(new Set(base.map((h) => h.ticker))).join(",");
        const r = await fetch(`${API}/market/quotes?tickers=${encodeURIComponent(names)}`, { headers: { Authorization: `Bearer ${token}` } });
        if (r.ok) {
          const rows: { ticker: string; price: number; synthetic?: boolean }[] = await r.json();
          // Placeholder prices must never be turned into a P&L: leave those holdings unpriced.
          placeholder = rows.some((q) => q.synthetic);
          quotes = Object.fromEntries(rows.filter((q) => !q.synthetic).map((q) => [q.ticker, q.price]));
        }
      } catch { /* fall back below */ }
      const withPrices = await Promise.all(
        base.map(async (h) => {
          if (quotes[h.ticker] !== undefined) return { ...h, current_price: quotes[h.ticker] };
          if (placeholder) return { ...h, loadError: true };
          try {
            const signal = await getSignal(token, h.ticker);
            return { ...h, current_price: signal.current_price };
          } catch {
            return { ...h, loadError: true };
          }
        })
      );
      setHoldings(withPrices);
      setPlaceholderPrices(placeholder);
      setPricesLoading(false);
    } catch {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    load();
  }, [load]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;
    setSubmitting(true);
    setError(null);
    try {
      await addPortfolioEntry(token, {
        ticker: form.ticker.toUpperCase(),
        quantity: Number(form.quantity),
        avg_buy_price: Number(form.avg_buy_price),
        buy_date: new Date(form.buy_date).toISOString(),
      });
      setForm({ ticker: "", quantity: "", avg_buy_price: "", buy_date: new Date().toISOString().slice(0, 10) });
      setShowForm(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add position");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemove = async (id: string) => {
    if (!token) return;
    await removePortfolioEntry(token, id);
    load();
  };

  const totals = React.useMemo(() => {
    const invested = holdings.reduce((s, h) => s + h.invested_value, 0);
    const current = holdings.reduce(
      (s, h) => s + (h.current_price ?? h.avg_buy_price) * h.quantity,
      0
    );
    return { invested, current, pnl: current - invested };
  }, [holdings]);
  // Totals are only meaningful when every holding has a real price; otherwise show "—", never a guess.
  const allPriced = holdings.length > 0 && holdings.every((h) => h.current_price !== undefined && !h.loadError);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold">Portfolio</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Your tracked positions, marked to the latest available price.
          </p>
        </div>
        <Button onClick={() => setShowForm((v) => !v)}>
          <Plus className="h-4 w-4" />
          Add position
        </Button>
      </div>

      {showForm && (
        <Card className="mb-6">
          <CardContent className="pt-5">
            <form onSubmit={handleAdd} className="grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
              <div>
                <Label className="mb-1.5 block">Ticker</Label>
                <Input
                  required
                  value={form.ticker}
                  onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })}
                  placeholder="RELIANCE"
                />
              </div>
              <div>
                <Label className="mb-1.5 block">Quantity</Label>
                <Input
                  required
                  type="number"
                  min="0.01"
                  step="any"
                  value={form.quantity}
                  onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                />
              </div>
              <div>
                <Label className="mb-1.5 block">Avg. buy price (₹)</Label>
                <Input
                  required
                  type="number"
                  min="0.01"
                  step="any"
                  value={form.avg_buy_price}
                  onChange={(e) => setForm({ ...form, avg_buy_price: e.target.value })}
                />
              </div>
              <div>
                <Label className="mb-1.5 block">Buy date</Label>
                <Input
                  required
                  type="date"
                  value={form.buy_date}
                  onChange={(e) => setForm({ ...form, buy_date: e.target.value })}
                />
              </div>
              <Button type="submit" disabled={submitting}>
                {submitting ? "Adding…" : "Add"}
              </Button>
            </form>
            {error && <p className="text-xs text-destructive mt-2">{error}</p>}
          </CardContent>
        </Card>
      )}

      {!loading && holdings.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center">
            <p className="text-sm text-muted-foreground">
              No positions tracked yet. Add one to start seeing live P&amp;L.
            </p>
          </CardContent>
        </Card>
      )}

      {holdings.length > 0 && (
        <>
          {placeholderPrices && (
            <div role="status" className="mb-4 rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-xs text-warning">
              This server has no real market data loaded, so current value and P&amp;L are not shown. Prices here would be placeholders, not your holdings&apos; real prices.
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            <Card>
              <CardHeader className="pb-1">
                <CardTitle>Invested</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="tabular text-xl font-semibold">
                  ₹{totals.invested.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1">
                <CardTitle>Current value</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="tabular text-xl font-semibold">
                  {allPriced ? `₹${totals.current.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "—"}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1">
                <CardTitle>Unrealized P&amp;L</CardTitle>
              </CardHeader>
              <CardContent>
                <p
                  className={`tabular text-xl font-semibold flex items-center gap-1 ${
                    !allPriced ? "" : totals.pnl >= 0 ? "text-success" : "text-destructive"
                  }`}
                >
                  {!allPriced && "—"}
                  {allPriced && (<>
                  {totals.pnl >= 0 ? (
                    <TrendingUp className="h-4 w-4" />
                  ) : (
                    <TrendingDown className="h-4 w-4" />
                  )}
                  ₹{Math.abs(totals.pnl).toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                  </>)}
                </p>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardContent className="pt-5 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground border-b border-border">
                    <th className="pb-2 pr-4 font-medium">Ticker</th>
                    <th className="pb-2 pr-4 font-medium text-right">Qty</th>
                    <th className="pb-2 pr-4 font-medium text-right">Avg. buy</th>
                    <th className="pb-2 pr-4 font-medium text-right">Current</th>
                    <th className="pb-2 pr-4 font-medium text-right">Invested</th>
                    <th className="pb-2 pr-4 font-medium text-right">P&amp;L</th>
                    <th className="pb-2 font-medium text-right"></th>
                  </tr>
                </thead>
                <tbody>
                  {holdings.map((h) => {
                    const current = h.current_price ?? h.avg_buy_price;
                    const currentValue = current * h.quantity;
                    const pnl = currentValue - h.invested_value;
                    const pnlPct = (pnl / h.invested_value) * 100;
                    return (
                      <tr key={h.id} className="border-b border-border/60 last:border-0">
                        <td className="py-2.5 pr-4 font-medium">{h.ticker}</td>
                        <td className="py-2.5 pr-4 text-right tabular">{h.quantity}</td>
                        <td className="py-2.5 pr-4 text-right tabular">₹{h.avg_buy_price.toFixed(2)}</td>
                        <td className="py-2.5 pr-4 text-right tabular">
                          {h.loadError ? (
                            <span className="text-muted-foreground text-xs">{placeholderPrices ? "no real price" : "no price"}</span>
                          ) : pricesLoading && h.current_price === undefined ? (
                            <span className="text-muted-foreground text-xs">…</span>
                          ) : (
                            `₹${current.toFixed(2)}`
                          )}
                        </td>
                        <td className="py-2.5 pr-4 text-right tabular">
                          ₹{h.invested_value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                        </td>
                        <td
                          className={`py-2.5 pr-4 text-right tabular font-medium ${
                            pnl >= 0 ? "text-success" : "text-destructive"
                          }`}
                        >
                          {h.current_price !== undefined
                            ? `${pnl >= 0 ? "+" : ""}${pnlPct.toFixed(1)}%`
                            : "—"}
                        </td>
                        <td className="py-2.5 text-right">
                          <button
                            onClick={() => handleRemove(h.id)}
                            className="text-muted-foreground hover:text-destructive transition-colors"
                            aria-label={`Remove ${h.ticker}`}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
