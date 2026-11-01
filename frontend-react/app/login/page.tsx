"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { demoOhlcv } from "@/lib/demo";

function Backdrop() {
  const pts = React.useMemo(() => {
    const c = demoOhlcv("NIFTYBEES", 200).map((x) => x.close);
    const min = Math.min(...c), max = Math.max(...c);
    return c.map((v, i) => `${(i / (c.length - 1)) * 1000},${380 - ((v - min) / (max - min)) * 300}`).join(" ");
  }, []);
  return (
    <svg viewBox="0 0 1000 400" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden>
      <defs>
        <linearGradient id="g" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#8b88f0" stopOpacity=".28" />
          <stop offset="1" stopColor="#8b88f0" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,400 ${pts} 1000,400`} fill="url(#g)" />
      <polyline points={pts} fill="none" stroke="#8b88f0" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const { signIn, token } = useAuth();
  const [email, setEmail] = React.useState("demo@intellistock.app");
  const [password, setPassword] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => { if (token) router.replace("/dashboard"); }, [token, router]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await signIn(email, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed. Check your email and password.");
    } finally {
      setSubmitting(false);
    }
  };

  const field = "h-11 w-full rounded-lg border border-border bg-card px-3 text-sm outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30";

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-border bg-sidebar lg:block">
        <Backdrop />
        <div className="relative flex h-full flex-col justify-between p-12">
          <span className="font-display grid h-11 w-11 place-items-center rounded-xl bg-primary text-xl font-extrabold text-primary-foreground">iS</span>
          <div className="max-w-md">
            <h2 className="font-display text-5xl font-bold leading-[1.05] tracking-tight">See where the price is likely to go, with the range.</h2>
            <p className="mt-5 text-muted-foreground">Forecasts, signals and backtests for NSE and BSE stocks. Every forecast shows its confidence band, not just a single number.</p>
          </div>
        </div>
      </section>
      <main className="flex items-center justify-center px-5 py-10">
        <form onSubmit={onSubmit} className="w-full max-w-sm space-y-5">
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight">Sign in</h1>
            <p className="mt-1 text-sm text-muted-foreground">Use the account your administrator created.</p>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="email" className="text-sm font-medium">Email</label>
            <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="password" className="text-sm font-medium">Password</label>
            <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
          </div>
          {error && <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
          <button type="submit" disabled={submitting}
            className="h-11 w-full rounded-lg bg-primary font-medium text-primary-foreground transition-[transform,opacity] duration-150 active:scale-[0.98] disabled:opacity-60 focus-visible:outline-2 outline-offset-2 outline-primary">
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </main>
    </div>
  );
}
