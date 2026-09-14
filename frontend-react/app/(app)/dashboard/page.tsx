"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpRight, ArrowDownRight, Minus } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { getWatchlist, getSignal, type SignalResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type Row = { ticker: string; signal?: SignalResponse; error?: boolean };

export default function DashboardPage() {
  const { token } = useAuth();
  const [rows, setRows] = React.useState<Row[]>([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!token) return;
    let cancelled = false;

    (async () => {
      setLoading(true);
      const wl = await getWatchlist(token).catch(() => ({ watchlist: [] }));
      const tickers = wl.watchlist.slice(0, 6).map((w) => w.ticker);
      const results = await Promise.all(
        tickers.map(async (ticker) => {
          try {
            const signal = await getSignal(token, ticker);
            return { ticker, signal };
          } catch {
            return { ticker, error: true };
          }
        })
      );
      if (!cancelled) {
        setRows(results);
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div>
      <div className="mb-8">
        <h1 className="font-display text-2xl font-semibold">Market dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">
          {new Date().toLocaleDateString("en-IN", {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric",
          })}{" "}
          · NSE/BSE
        </p>
      </div>

      {loading && <p className="text-sm text-muted-foreground">Loading watchlist signals…</p>}

      {!loading && rows.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center">
            <p className="text-sm text-muted-foreground">
              Your watchlist is empty. Add a ticker from the sidebar to see it here.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {rows.map((row) => (
          <Link key={row.ticker} href={`/predictions?ticker=${row.ticker}`}>
            <Card className="hover:border-primary/40 transition-colors cursor-pointer h-full">
              <CardHeader className="pb-1 flex flex-row items-center justify-between">
                <CardTitle className="text-foreground text-base">{row.ticker}</CardTitle>
                {row.signal && <SignalPill signal={row.signal.signal} />}
              </CardHeader>
              <CardContent>
                {row.error && (
                  <p className="text-xs text-muted-foreground">No model available for this ticker.</p>
                )}
                {row.signal && (
                  <div className="flex items-baseline justify-between">
                    <span className="tabular text-2xl font-semibold">
                      ₹{row.signal.current_price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
                    </span>
                    <span
                      className={
                        "tabular text-sm font-medium flex items-center gap-0.5 " +
                        (row.signal.predicted_return_pct >= 0 ? "text-success" : "text-destructive")
                      }
                    >
                      {row.signal.predicted_return_pct >= 0 ? (
                        <ArrowUpRight className="h-3.5 w-3.5" />
                      ) : (
                        <ArrowDownRight className="h-3.5 w-3.5" />
                      )}
                      {row.signal.predicted_return_pct.toFixed(2)}%
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <p className="mt-8 text-xs text-muted-foreground">
        Click any ticker to view its full forecast, confidence interval, and technical indicators.
      </p>
    </div>
  );
}

function SignalPill({ signal }: { signal: "BUY" | "SELL" | "HOLD" }) {
  const map = {
    BUY: { variant: "success-light" as const, Icon: ArrowUpRight },
    SELL: { variant: "destructive-light" as const, Icon: ArrowDownRight },
    HOLD: { variant: "warning-light" as const, Icon: Minus },
  };
  const { variant, Icon } = map[signal];
  return (
    <Badge variant={variant}>
      <Icon className="h-3 w-3" />
      {signal}
    </Badge>
  );
}
