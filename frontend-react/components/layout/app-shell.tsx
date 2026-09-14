"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LayoutDashboard, LineChart, History, Settings, LogOut, TrendingUp, Plus, Briefcase } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { addToWatchlist, getWatchlist } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/predictions", label: "Predictions", icon: LineChart },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase },
  { href: "/backtesting", label: "Backtesting", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { token, user, signOut, loading } = useAuth();
  const [watchlist, setWatchlist] = React.useState<{ id: string; ticker: string }[]>([]);
  const [newTicker, setNewTicker] = React.useState("");
  const [adding, setAdding] = React.useState(false);

  React.useEffect(() => {
    if (!loading && !token) router.replace("/login");
  }, [loading, token, router]);

  const refreshWatchlist = React.useCallback(() => {
    if (!token) return;
    getWatchlist(token)
      .then((r) => setWatchlist(r.watchlist))
      .catch(() => setWatchlist([]));
  }, [token]);

  React.useEffect(() => {
    refreshWatchlist();
  }, [refreshWatchlist]);

  const handleAdd = async () => {
    if (!token || !newTicker.trim()) return;
    setAdding(true);
    try {
      await addToWatchlist(token, newTicker.trim().toUpperCase());
      setNewTicker("");
      refreshWatchlist();
    } catch {
      // silently ignore — duplicate ticker etc.
    } finally {
      setAdding(false);
    }
  };

  if (loading || !token) {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-muted-foreground text-sm">
        Loading…
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="w-64 shrink-0 border-r border-border flex flex-col">
        <div className="px-5 py-5 border-b border-border">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-primary" />
            <span className="font-display text-lg font-semibold">IntelliStock</span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">NSE/BSE Market Intelligence</p>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname?.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:text-foreground hover:bg-popover"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="px-3 pb-3">
          <p className="px-3 pb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Watchlist
          </p>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {watchlist.length === 0 && (
              <p className="px-3 text-xs text-muted-foreground">No tickers yet.</p>
            )}
            {watchlist.map((w) => (
              <Link
                key={w.id}
                href={`/predictions?ticker=${w.ticker}`}
                className="block rounded-md px-3 py-1.5 text-sm text-foreground hover:bg-popover"
              >
                {w.ticker}
              </Link>
            ))}
          </div>
          <div className="mt-2 flex gap-1.5 px-1">
            <Input
              value={newTicker}
              onChange={(e) => setNewTicker(e.target.value)}
              placeholder="e.g. WIPRO"
              className="h-8 text-xs"
              onKeyDown={(e) => e.key === "Enter" && handleAdd()}
            />
            <Button size="icon" variant="secondary" className="h-8 w-8 shrink-0" onClick={handleAdd} disabled={adding}>
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        <div className="border-t border-border px-5 py-4">
          <p className="text-sm font-medium truncate">{user?.full_name || user?.email}</p>
          <button
            onClick={() => {
              signOut();
              router.replace("/login");
            }}
            className="mt-2 flex items-center gap-2 text-xs text-muted-foreground hover:text-destructive transition-colors"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-8 py-8">{children}</div>
      </main>
    </div>
  );
}
