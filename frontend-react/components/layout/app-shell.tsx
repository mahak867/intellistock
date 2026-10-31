"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LayoutDashboard, LineChart, History, Settings, LogOut, Briefcase } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Terminal", icon: LayoutDashboard },
  { href: "/predictions", label: "Predictions", icon: LineChart },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase },
  { href: "/backtesting", label: "Backtesting", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { token, user, signOut, loading } = useAuth();
  const demo = process.env.NEXT_PUBLIC_DEMO === "1";

  React.useEffect(() => {
    if (!demo && !loading && !token) router.replace("/login");
  }, [demo, loading, token, router]);

  if (!demo && (loading || !token)) {
    return <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>;
  }

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-[68px] shrink-0 flex-col items-center border-r border-border bg-sidebar py-4">
        <Link href="/dashboard" aria-label="IntelliStock home"
          className="font-display grid h-10 w-10 place-items-center rounded-xl bg-primary text-lg font-extrabold text-primary-foreground">
          iS
        </Link>
        <nav className="mt-8 flex flex-1 flex-col gap-1.5" aria-label="Main">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname?.startsWith(href);
            return (
              <Link key={href} href={href} aria-label={label} title={label} aria-current={active ? "page" : undefined}
                className={cn(
                  "group relative grid h-11 w-11 place-items-center rounded-lg transition-[background-color,color,transform] duration-150 active:scale-[0.96] focus-visible:outline-2 outline-primary",
                  active ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}>
                <Icon className="h-[18px] w-[18px]" />
                {active && <span className="absolute -left-[13px] h-5 w-[3px] rounded-r bg-primary" />}
              </Link>
            );
          })}
        </nav>
        <button
          onClick={() => { signOut(); router.replace("/login"); }}
          aria-label={`Sign out ${user?.full_name || user?.email || ""}`.trim()} title="Sign out"
          className="grid h-11 w-11 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-destructive focus-visible:outline-2 outline-primary">
          <LogOut className="h-[18px] w-[18px]" />
        </button>
      </aside>
      <main className="min-w-0 flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-[1400px] px-5 py-6 sm:px-8 sm:py-8">{children}</div>
      </main>
    </div>
  );
}
