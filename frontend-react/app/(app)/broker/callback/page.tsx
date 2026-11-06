"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { finishBrokerLogin } from "@/lib/api";

// Zerodha sends the browser here after login: /broker/callback?request_token=...&action=login&status=success
// Set this page's full address as the Redirect URL of your Kite Connect app.
function Callback() {
  const { token } = useAuth();
  const params = useSearchParams();
  const router = useRouter();
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);
  const started = React.useRef(false);

  React.useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    const rt = params.get("request_token");
    const st = params.get("status");
    const done = (ok: boolean, text: string) => setMsg({ ok, text });
    if (st !== "success" || !rt) {
      Promise.resolve().then(() => done(false, "Zerodha did not finish the login. Try again from the Broker page."));
      return;
    }
    finishBrokerLogin(token, rt)
      .then((r) => { done(true, r.message); setTimeout(() => router.replace("/broker"), 1200); })
      .catch((e) => done(false, e instanceof Error ? e.message : "Login failed"));
  }, [token, params, router]);

  return (
    <div className="mx-auto max-w-md space-y-4 py-10">
      <h1 className="font-display text-2xl font-semibold">Connecting Zerodha</h1>
      {!msg && <p className="text-sm text-muted-foreground">Finishing the login…</p>}
      {msg && <p role="status" className={msg.ok ? "text-sm text-success" : "text-sm text-destructive"}>{msg.text}</p>}
      <Link href="/broker" className="text-sm text-primary underline-offset-4 hover:underline">Back to Broker</Link>
    </div>
  );
}

export default function BrokerCallbackPage() {
  return <React.Suspense fallback={null}><Callback /></React.Suspense>;
}
