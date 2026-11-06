"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { getFundamentals, getNews, type Fundamentals, type NewsView } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const fmt = (v: number | null | undefined, suf = "") => (v == null ? "—" : `${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}${suf}`);

const ROWS: [keyof Fundamentals, string, string][] = [
  ["price", "Price (₹)", ""], ["market_cap_cr", "Market cap (₹ crore)", ""], ["pe", "P/E", ""], ["forward_pe", "Forward P/E", ""],
  ["pb", "Price to book", ""], ["roe", "Return on equity", "%"], ["roa", "Return on assets", "%"], ["debt_equity", "Debt to equity", ""],
  ["profit_margin", "Profit margin", "%"], ["operating_margin", "Operating margin", "%"], ["sales_growth", "Revenue growth (yearly)", "%"],
  ["earnings_growth", "Earnings growth (yearly)", "%"], ["dividend_yield", "Dividend yield", "%"], ["insider_holding", "Insider holding", "%"], ["beta", "Beta", ""],
];

function Research() {
  const { token } = useAuth();
  const params = useSearchParams();
  const [q, setQ] = React.useState(params.get("ticker") ?? "TCS");
  const [sym, setSym] = React.useState((params.get("ticker") ?? "TCS").toUpperCase());
  const [f, setF] = React.useState<Fundamentals | null>(null);
  const [fErr, setFErr] = React.useState<string | null>(null);
  const [n, setN] = React.useState<NewsView | null>(null);
  React.useEffect(() => {
    let live = true;
    Promise.resolve().then(() => { if (live) { setF(null); setN(null); setFErr(null); } });
    getFundamentals(token, sym).then((x) => live && setF(x)).catch((e) => live && setFErr(e instanceof Error ? e.message : "No fundamentals"));
    getNews(token, sym).then((x) => live && setN(x)).catch(() => live && setN({ ticker: sym, news: [], announcements: [], errors: ["News unavailable."] }));
    return () => { live = false; };
  }, [token, sym]);
  return (
    <div className="min-w-0 space-y-6">
      <header>
        <h1 className="font-display text-3xl font-bold tracking-tight">Research</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Company numbers, recent headlines and exchange announcements for one stock.</p>
      </header>
      <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) setSym(q.trim().toUpperCase()); }} className="flex max-w-md gap-2">
        <input aria-label="Stock symbol" maxLength={20} autoCapitalize="characters" spellCheck={false} value={q} onChange={(e) => setQ(e.target.value)} className="h-10 min-w-0 flex-1 rounded-lg border border-border bg-card px-3 text-sm" />
        <Button type="submit">Look up</Button>
      </form>
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <Card className="h-fit min-w-0">
          <CardHeader><CardTitle className="text-base text-foreground">{f?.name ?? sym}</CardTitle></CardHeader>
          <CardContent className="text-sm">
            {fErr && <p className="text-destructive">{fErr}</p>}
            {!f && !fErr && <p className="text-muted-foreground">Loading…</p>}
            {f && (
              <>
                <p className="mb-3 text-xs text-muted-foreground">{[f.sector, f.industry].filter(Boolean).join(" · ")}</p>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
                  {ROWS.map(([k, label, suf]) => (<React.Fragment key={k}><dt className="text-muted-foreground">{label}</dt><dd className="font-num text-right">{fmt(f[k] as number | null, suf)}</dd></React.Fragment>))}
                </dl>
                <p className="mt-3 text-xs text-muted-foreground">Source: {f.source}, its own compilation, updated daily here. Check the annual report before relying on a figure. Insider holding is Yahoo&apos;s field, not SEBI&apos;s promoter holding.</p>
              </>
            )}
          </CardContent>
        </Card>
        <div className="min-w-0 space-y-6">
          <Card className="min-w-0">
            <CardHeader><CardTitle className="text-base text-foreground">Exchange announcements</CardTitle></CardHeader>
            <CardContent className="text-sm">
              {!n ? <p className="text-muted-foreground">Loading…</p> : n.announcements.length === 0 ? <p className="text-muted-foreground">{n.errors.find((e) => e.includes("NSE")) ?? "No recent announcements."}</p> : (
                <ul className="space-y-2">{n.announcements.map((a, i) => (
                  <li key={i} className="border-b border-border pb-2 last:border-0"><p className="font-medium">{a.url ? <a href={a.url} target="_blank" rel="noopener noreferrer" className="hover:text-primary">{a.title}</a> : a.title}</p>
                    {a.detail && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{a.detail}</p>}<p className="font-num text-xs text-muted-foreground">{a.published}</p></li>))}</ul>
              )}
            </CardContent>
          </Card>
          <Card className="min-w-0">
            <CardHeader><CardTitle className="text-base text-foreground">Headlines</CardTitle></CardHeader>
            <CardContent className="text-sm">
              {!n ? <p className="text-muted-foreground">Loading…</p> : n.news.length === 0 ? <p className="text-muted-foreground">{n.errors.find((e) => e.startsWith("News")) ?? "No recent headlines."}</p> : (
                <ul className="space-y-2">{n.news.map((a) => (
                  <li key={a.url} className="border-b border-border pb-2 last:border-0"><a href={a.url} target="_blank" rel="noopener noreferrer" className="font-medium hover:text-primary">{a.title}</a>
                    <p className="text-xs text-muted-foreground">{[a.source, a.published ? new Date(a.published).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : null].filter(Boolean).join(" · ")}</p></li>))}</ul>
              )}
              <p className="mt-3 text-xs text-muted-foreground">From Google News search. Headlines are not checked by IntelliStock.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export default function ResearchPage() {
  return <React.Suspense fallback={null}><Research /></React.Suspense>;
}
