"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { LayoutDashboard, LineChart, History, Settings, LogOut, Briefcase, Calculator, BellRing, LifeBuoy, Ellipsis } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Terminal", icon: LayoutDashboard },
  { href: "/predictions", label: "Predictions", icon: LineChart },
  { href: "/tools", label: "Tools", icon: Calculator },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase },
  { href: "/alerts", label: "Alerts", icon: BellRing },
  { href: "/backtesting", label: "Backtesting", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/help", label: "Help", icon: LifeBuoy },
];

// On a phone the bar holds the five places people use most; the rest sit behind "More".
const BAR = ["/dashboard", "/tools", "/portfolio", "/alerts"];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { token, user, signOut, loading } = useAuth();
  const demo = process.env.NEXT_PUBLIC_DEMO === "1";
  const [more, setMore] = React.useState(false);

  React.useEffect(() => {
    if (!demo && !loading && !token) router.replace("/login");
  }, [demo, loading, token, router]);

  if (!demo && (loading || !token)) {
    return <div className="flex h-dvh items-center justify-center text-sm text-muted-foreground">Loading…</div>;
  }

  const leave = () => { signOut(); router.replace("/login"); };
  const is = (href: string) => !!pathname?.startsWith(href);
  const moreActive = NAV.some((n) => !BAR.includes(n.href) && is(n.href));

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-[68px] shrink-0 flex-col items-center border-r border-border bg-sidebar py-4 md:flex">
        <Link href="/dashboard" aria-label="IntelliStock home"
          className="font-display grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary text-lg font-extrabold text-primary-foreground">
          iS
        </Link>
        <nav className="no-scrollbar mt-6 flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto py-1" aria-label="Main">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = is(href);
            return (
              <Link key={href} href={href} aria-label={label} title={label} aria-current={active ? "page" : undefined}
                className={cn(
                  "group relative grid h-11 w-11 shrink-0 place-items-center rounded-lg transition-[background-color,color,transform] duration-150 active:scale-[0.96] focus-visible:outline-2 outline-primary",
                  active ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}>
                <Icon className="h-[18px] w-[18px]" />
                {active && <span className="absolute -left-[13px] h-5 w-[3px] rounded-r bg-primary" />}
              </Link>
            );
          })}
        </nav>
        <button
          onClick={leave}
          aria-label={`Sign out ${user?.full_name || user?.email || ""}`.trim()} title="Sign out"
          className="grid h-11 w-11 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-destructive focus-visible:outline-2 outline-primary">
          <LogOut className="h-[18px] w-[18px]" />
        </button>
      </aside>

      <main className="min-w-0 flex-1 overflow-x-hidden pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:pb-0">
        <div className="mx-auto max-w-[1400px] px-4 py-5 sm:px-8 sm:py-8">{children}</div>
      </main>

      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-sidebar/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        <ul className="mx-auto grid max-w-md grid-cols-5">
          {NAV.filter((n) => BAR.includes(n.href)).map(({ href, label, icon: Icon }) => {
            const active = is(href);
            return (
              <li key={href}>
                <Link href={href} aria-current={active ? "page" : undefined}
                  className={cn("tap flex h-[3.5rem] flex-col items-center justify-center gap-0.5 text-[11px] transition-colors duration-150 focus-visible:outline-2 outline-primary", active ? "text-primary" : "text-muted-foreground")}>
                  <Icon className="h-5 w-5" aria-hidden />{label}
                </Link>
              </li>
            );
          })}
          <li>
            <button onClick={() => setMore(true)} aria-haspopup="dialog" aria-expanded={more}
              className={cn("tap flex h-[3.5rem] w-full flex-col items-center justify-center gap-0.5 text-[11px] transition-colors duration-150 focus-visible:outline-2 outline-primary", moreActive ? "text-primary" : "text-muted-foreground")}>
              <Ellipsis className="h-5 w-5" aria-hidden />More
            </button>
          </li>
        </ul>
      </nav>

      <Dialog.Root open={more} onOpenChange={setMore}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 data-[state=open]:animate-in data-[state=open]:fade-in-0 md:hidden" />
          <Dialog.Content className="fixed inset-x-0 bottom-0 z-50 rounded-t-2xl border-t border-border bg-popover px-3 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3 outline-none data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom md:hidden">
            <Dialog.Title className="px-2 pb-2 text-sm font-medium text-muted-foreground">More</Dialog.Title>
            <Dialog.Description className="sr-only">Other pages and sign out</Dialog.Description>
            <ul className="space-y-1">
              {NAV.filter((n) => !BAR.includes(n.href)).map(({ href, label, icon: Icon }) => (
                <li key={href}>
                  <Link href={href} aria-current={is(href) ? "page" : undefined} onClick={() => setMore(false)}
                    className={cn("tap flex h-12 items-center gap-3 rounded-lg px-3 text-[15px]", is(href) ? "bg-primary/15 text-primary" : "text-foreground active:bg-accent")}>
                    <Icon className="h-5 w-5" aria-hidden />{label}
                  </Link>
                </li>
              ))}
              <li>
                <button onClick={leave} className="tap flex h-12 w-full items-center gap-3 rounded-lg px-3 text-[15px] text-destructive active:bg-accent">
                  <LogOut className="h-5 w-5" aria-hidden />Sign out{user?.full_name ? ` (${user.full_name})` : ""}
                </button>
              </li>
            </ul>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
